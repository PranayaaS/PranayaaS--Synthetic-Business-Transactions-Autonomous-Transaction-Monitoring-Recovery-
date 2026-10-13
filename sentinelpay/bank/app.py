"""Mock cooperative bank (port 8001): customer pages, payment API, chaos modes, recovery, logging."""
import asyncio
import logging
import random
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bank import chaos
from common import config, db

app = FastAPI(title="DDCCB Mock Bank")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

DEMO_USER, DEMO_PASS = "demo", "demo123"
BANKS = ["DDCCB", "Bank X", "Bank Y", "SBI"]
TXNS = {}  # txn_ref -> payment record (in-memory receipts)

file_log = logging.getLogger("bank")
if not file_log.handlers:
    _h = logging.FileHandler(config.LOG_DIR / "bank.log", encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    file_log.addHandler(_h)
    file_log.setLevel(logging.INFO)

QUIET = {("GET", "/api/chaos"), ("GET", "/health"), ("GET", "/favicon.ico")}


def log_event(endpoint, method, status, duration_ms, layer_hint="none", message=""):
    file_log.info("%s %s %s %dms layer=%s %s", method, endpoint, status, duration_ms, layer_hint, message)
    try:
        db.insert("bank_logs", ts=db.iso(), endpoint=endpoint, method=method, http_status=status,
                  duration_ms=duration_ms, layer_hint=layer_hint, message=message)
    except Exception as e:  # logging must never break the bank
        file_log.warning("db log failed: %s", e)


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    request.state.layer_hint = "none"
    request.state.log_message = ""
    response = await call_next(request)
    if (request.method, request.url.path) not in QUIET:
        path = "/receipt" if request.url.path.startswith("/receipt/") else request.url.path
        log_event(path, request.method, response.status_code, int((time.perf_counter() - start) * 1000),
                  request.state.layer_hint, request.state.log_message)
    return response


_client = None


async def active_notices():
    global _client
    try:
        if _client is None:
            _client = httpx.AsyncClient(timeout=0.8, trust_env=False)
        r = await _client.get(f"{config.MONITOR_URL}/api/notices/active")
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def logged_in(request):
    return request.cookies.get("session") == "demo-session"


# ------------------------------------------------------------------ pages

@app.get("/health")
async def health():
    return {"ok": True, "service": "bank", "chaos": chaos.mode()}


@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "login.html", {"error": error, "notices": await active_notices()})


@app.post("/login")
async def login(request: Request, username: str = Form(""), password: str = Form("")):
    if chaos.mode() == "server_error":
        request.state.layer_hint = "server"
        request.state.log_message = "Internal server error: application server not responding"
        return HTMLResponse("<h1>500 Internal Server Error</h1><p>Bank application server error.</p>", status_code=500)
    if username != DEMO_USER or password != DEMO_PASS:
        request.state.log_message = "invalid credentials"
        return RedirectResponse("/?error=Invalid+credentials", status_code=303)
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie("session", "demo-session", httponly=True)
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("session")
    return resp


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not logged_in(request):
        return RedirectResponse("/", status_code=303)
    recent = list(TXNS.values())[-5:][::-1]
    return templates.TemplateResponse(request, "dashboard.html",
                                      {"notices": await active_notices(), "recent": recent})


@app.get("/transfer", response_class=HTMLResponse)
async def transfer(request: Request):
    if not logged_in(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "transfer.html", {"banks": BANKS, "notices": await active_notices()})


@app.get("/receipt/{txn_ref}", response_class=HTMLResponse)
async def receipt(request: Request, txn_ref: str):
    t = TXNS.get(txn_ref)
    if not t:
        return HTMLResponse("<h1>Receipt not found</h1>", status_code=404)
    shown = dict(t)
    if chaos.mode() == "wrong_amount":
        shown["amount"] = t["amount"] + 1
        request.state.layer_hint = "server"
        request.state.log_message = f"receipt service rendered amount {shown['amount']} for txn amount {t['amount']}"
    return templates.TemplateResponse(request, "receipt.html", {"t": shown})


@app.get("/chaos", response_class=HTMLResponse)
async def chaos_page(request: Request):
    return templates.TemplateResponse(request, "chaos.html", {"state": chaos.get()})


# ------------------------------------------------------------------ payment API

def _err(request, status, code, message, layer):
    request.state.layer_hint = layer
    request.state.log_message = f"{code}: {message}"
    return JSONResponse({"status": "failed", "error_code": code, "message": message}, status_code=status)


@app.post("/api/pay")
async def pay(request: Request):
    body = await request.json()
    try:
        amount = int(body.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0
    bank = body.get("receiver_bank", "DDCCB")
    ref = body.get("ref") or ""
    mode = chaos.mode()
    if amount <= 0:
        return _err(request, 400, "BAD_AMOUNT", "Amount must be positive", "none")

    if mode == "gateway_down":
        return _err(request, 502, "GW_UNAVAILABLE", "Payment gateway unavailable", "gateway")
    if mode == "intermittent" and random.random() < 0.4:
        return _err(request, 502, "GW_UNAVAILABLE", "Payment gateway unavailable (intermittent)", "gateway")
    if mode == "gateway_timeout":
        await asyncio.sleep(8)
        request.state.layer_hint = "gateway"
        request.state.log_message = "Payment gateway response exceeded 8000ms"
    if mode == "slow_gateway":
        n = chaos.next_pay_call()
        delay = min(2.5 + 0.35 * (n - 1), 3.5) + random.uniform(0, 0.05)
        await asyncio.sleep(delay)
        request.state.layer_hint = "gateway"
        request.state.log_message = f"Payment gateway slow response {int(delay * 1000)}ms"
    if bank == "Bank X" and chaos.is_paused("Bank X"):
        txn_ref = "TXN" + uuid.uuid4().hex[:10].upper()
        TXNS[txn_ref] = {"txn_ref": txn_ref, "amount": amount, "receiver_bank": bank, "status": "QUEUED",
                         "receiver_name": body.get("receiver_name", ""), "client_ref": ref,
                         "note": "Transfers to Bank X are temporarily paused. Your payment is queued and will be sent automatically."}
        request.state.layer_hint = "receiver_bank"
        request.state.log_message = "Bank X paused by operations: payment queued"
        return {"status": "queued", "txn_ref": txn_ref, "amount": amount, "receiver_bank": bank,
                "message": TXNS[txn_ref]["note"]}
    if mode == "receiver_bank_down" and bank == "Bank X":
        return _err(request, 503, "RB_UNAVAILABLE", "Receiver bank Bank X not responding", "receiver_bank")
    if mode == "large_amount_fail" and amount > 50_000:
        return _err(request, 422, "LIMIT_OR_RISK_CHECK", "Transfer blocked by limit / risk rule", "server")

    txn_ref = "TXN" + uuid.uuid4().hex[:10].upper()
    TXNS[txn_ref] = {"txn_ref": txn_ref, "amount": amount, "receiver_bank": bank, "status": "SUCCESS",
                     "receiver_name": body.get("receiver_name", ""), "client_ref": ref, "note": ""}
    if len(TXNS) > 500:
        TXNS.pop(next(iter(TXNS)))
    return {"status": "success", "txn_ref": txn_ref, "amount": amount, "receiver_bank": bank}


# ------------------------------------------------------------------ chaos + recovery

@app.get("/api/chaos")
async def get_chaos():
    return chaos.get()


@app.post("/api/chaos/{mode}")
async def set_chaos(request: Request, mode: str):
    try:
        state = chaos.set_mode(mode)
    except ValueError:
        return JSONResponse({"error": f"unknown mode {mode}"}, status_code=400)
    request.state.log_message = f"chaos mode set to {mode}"
    return state


@app.post("/api/recovery/{action}")
async def recovery(request: Request, action: str):
    try:
        cleared, msg = chaos.recover(action)
    except ValueError:
        return JSONResponse({"error": f"unknown action {action}"}, status_code=400)
    request.state.layer_hint = "none"
    request.state.log_message = f"RECOVERY {action}: {msg}"
    return {"action": action, "cleared": cleared, "message": msg, "chaos": chaos.get()}
