"""Synthetic probes: headless Chromium walks login -> transfer -> pay -> receipt.

Runs in a dedicated thread with its own asyncio loop (Proactor on Windows, required by
Playwright), so probe cycles never block the dashboard API.
"""
import asyncio
import re
import sys
import threading
import time
import traceback
import uuid
from urllib.parse import urlparse

import httpx

from common import config, db
from monitor import detector, events

T = config.STEP_TIMEOUT_MS


LOCAL_HOSTS = {urlparse(config.BANK_URL).hostname, "127.0.0.1", "localhost"}


async def _local_only(route):
    if urlparse(route.request.url).hostname in LOCAL_HOSTS:
        await route.continue_()
    else:
        await route.abort()


class StepError(Exception):
    def __init__(self, message, http=None):
        super().__init__(message)
        self.http = http


class Prober:
    def __init__(self):
        self.trigger = threading.Event()
        self.thread = None
        self.browser = None
        self.running = False
        self.last_cycle_at = None
        self.next_cycle_at = None
        self.cycles = 0
        self.unreachable_streak = 0
        self.unreachable_since = None
        self.status = "starting"
        self.http = None

    # ------------------------------------------------------------- lifecycle
    def start(self):
        if self.thread:
            return
        self.thread = threading.Thread(target=self._thread_main, name="probe", daemon=True)
        self.thread.start()

    def run_now(self):
        self.trigger.set()

    def _thread_main(self):
        loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._main())
        except Exception:
            traceback.print_exc()
            self.status = "crashed"

    async def _main(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            self.browser = await pw.chromium.launch(headless=True)
            self.status = "idle"
            events.emit("info", "PROBE_SYNC", "Headless Chromium launched; synthetic probes armed")
            await asyncio.sleep(2)  # let the bank finish starting
            while True:
                try:
                    await self.cycle()
                except Exception as e:
                    traceback.print_exc()
                    events.emit("warn", "PROBE", f"Probe cycle error: {e}")
                self.next_cycle_at = time.time() + config.PROBE_INTERVAL_SEC
                await asyncio.get_running_loop().run_in_executor(None, self.trigger.wait, config.PROBE_INTERVAL_SEC)
                self.trigger.clear()

    # ------------------------------------------------------------- cycle
    async def _get(self, url, timeout=3.0):
        if self.http is None:
            self.http = httpx.AsyncClient(trust_env=False)
        return await self.http.get(url, timeout=timeout)

    async def cycle(self):
        self.running = True
        self.status = "running"
        try:
            await self._cycle()
        finally:
            self.running = False
            self.status = "idle"
            self.cycles += 1
            self.last_cycle_at = db.iso()

    async def _cycle(self):
        # False-alarm protection, part 1: probe self-check.
        try:
            await self._get(f"{config.MONITOR_URL}/api/ping", 2)
        except Exception as e:
            events.emit("warn", "PROBE_NET", f"Probe network issue – ignored ({e.__class__.__name__})")
            return
        login_j = db.q1("SELECT id FROM journeys WHERE name='Login'")
        try:
            await self._get(f"{config.BANK_URL}/health", 3)
            chaos = (await self._get(f"{config.BANK_URL}/api/chaos", 3)).json()
        except Exception as e:
            self.unreachable_streak += 1
            self.unreachable_since = self.unreachable_since or db.iso()
            err = f"Bank unreachable ({e.__class__.__name__}: connection refused or timed out)"
            db.insert("runs", journey_id=login_j["id"], run_group=uuid.uuid4().hex, step="login", status="probe_error",
                      latency_ms=0, error=err, http_status=None, ts=db.iso(), attempt=1)
            detector.on_bank_unreachable(self.unreachable_streak, err, login_j["id"], self.unreachable_since)
            return
        if self.unreachable_streak:
            events.emit("ok", "PROBE_NET", "Bank reachable again")
        self.unreachable_streak, self.unreachable_since = 0, None
        detector.on_bank_reachable()

        any_fail = False
        owners = {}
        for name, steps in db.CORE_STEP_MAP.items():
            j = db.q1("SELECT id FROM journeys WHERE name=?", (name,))
            for s in steps:
                owners[s] = j["id"]
        base = {"id": None, "name": "Core payment journey", "amount": 500, "receiver_bank": "DDCCB"}
        flows = [(base, lambda s: owners[s])]
        for j in db.q("SELECT * FROM journeys WHERE auto_created=1 AND active=1 ORDER BY id"):
            flows.append((j, (lambda jid: (lambda s: jid))(j["id"])))

        for journey, owner in flows:
            attempts = [await self.run_flow(journey, owner, 1)]
            # False-alarm protection, part 2: retry up to 2 more times; confirm only if 2 of 3 fail.
            if attempts[0]["failed"]:
                for n in (2, 3):
                    attempts.append(await self.run_flow(journey, owner, n))
                    fails = sum(1 for a in attempts if a["failed"])
                    if fails >= 2 or (n == 3):
                        break
            if attempts[0]["failed"]:
                any_fail = any_fail or sum(1 for a in attempts if a["failed"]) >= 2
            detector.evaluate(journey, attempts, chaos, owner)
        detector.after_cycle({"any_fail": any_fail})

    # ------------------------------------------------------------- one journey walk
    async def run_flow(self, journey, owner, attempt):
        group = uuid.uuid4().hex
        amount, bank = int(journey["amount"]), journey["receiver_bank"]
        steps, current = [], None
        result = {"group": group, "steps": steps, "failed": False, "failed_step": None, "error": None,
                  "http": None, "screenshot": None, "journey": journey["name"], "attempt": attempt}
        ctx = await self.browser.new_context(viewport={"width": 1100, "height": 760})
        # Only the bank itself is measured: third-party assets (CDN CSS, fonts) are blocked so the probe
        # is not skewed by internet speed and works offline.
        await ctx.route("**/*", _local_only)
        page = await ctx.new_page()
        page.set_default_timeout(T)

        def record(step, t0, http=200):
            lat = int((time.perf_counter() - t0) * 1000)
            status = "slow" if lat > config.SLOW_THRESHOLD_MS else "pass"
            steps.append({"step": step, "status": status, "latency_ms": lat, "error": None, "http": http})

        t0 = time.perf_counter()
        try:
            current = "login"
            t0 = time.perf_counter()
            await page.goto(f"{config.BANK_URL}/", timeout=T, wait_until="domcontentloaded")
            await page.fill("#username", "demo")
            await page.fill("#password", "demo123")
            async with page.expect_response(lambda r: r.url.rstrip("/").endswith("/login") and r.request.method == "POST",
                                            timeout=T) as ri:
                await page.click("#login-btn")
            resp = await ri.value
            if resp.status >= 400:
                raise StepError(f"HTTP {resp.status} on POST /login (bank application server error)", resp.status)
            await page.wait_for_url("**/dashboard", timeout=T, wait_until="domcontentloaded")
            record("login", t0, resp.status)

            current = "open_transfer"
            t0 = time.perf_counter()
            await page.click("#transfer-link")
            await page.wait_for_selector("#pay-btn", timeout=T)
            record("open_transfer", t0)

            current = "submit_transfer"
            t0 = time.perf_counter()
            await page.fill("#receiver-name", "SentinelPay Probe")
            await page.select_option("#receiver-bank", bank)
            await page.fill("#amount", str(amount))
            record("submit_transfer", t0)

            current = "gateway_pay"
            t0 = time.perf_counter()
            async with page.expect_response(lambda r: "/api/pay" in r.url, timeout=T) as pi:
                await page.click("#pay-btn")
            pr = await pi.value
            if pr.status != 200:
                try:
                    body = await pr.json()
                except Exception:
                    body = {}
                code = body.get("error_code", "")
                raise StepError(f"HTTP {pr.status}: {body.get('message', 'payment failed')}" + (f" [{code}]" if code else ""),
                                pr.status)
            record("gateway_pay", t0, pr.status)
            self._synthetic_txn(amount, bank, "success")

            current = "verify_receipt"
            t0 = time.perf_counter()
            await page.wait_for_url("**/receipt/**", timeout=T, wait_until="domcontentloaded")
            shown_txt = await page.inner_text("#receipt-amount", timeout=T)
            status_txt = (await page.inner_text("#receipt-status", timeout=T)).strip().upper()
            shown = int(re.sub(r"[^\d]", "", shown_txt) or 0)
            if shown != amount:
                raise StepError(f"Receipt amount mismatch: shown {shown} != submitted {amount}", 200)
            if status_txt not in ("SUCCESS", "QUEUED"):
                raise StepError(f"Receipt status {status_txt} is not SUCCESS", 200)
            record("verify_receipt", t0)
        except Exception as e:
            lat = int((time.perf_counter() - t0) * 1000)
            if isinstance(e, StepError):
                err, http = str(e), e.http
            elif "Timeout" in e.__class__.__name__ or "timeout" in str(e).lower():
                err = (f"Timeout {T}ms waiting for /api/pay (payment gateway did not respond)" if current == "gateway_pay"
                       else f"Timeout {T}ms at step {current}")
                http = None
            else:
                err, http = f"{e.__class__.__name__}: {str(e).splitlines()[0][:200]}", None
            if current == "gateway_pay":
                self._synthetic_txn(amount, bank, "failed")
            shot = f"{group}.png"
            try:
                await page.screenshot(path=str(config.SHOT_DIR / shot), full_page=True)
            except Exception:
                shot = None
            steps.append({"step": current, "status": "fail", "latency_ms": lat, "error": err, "http": http,
                          "screenshot": shot})
            result.update(failed=True, failed_step=current, error=err, http=http, screenshot=shot)
        finally:
            try:
                await ctx.close()
            except Exception:
                pass

        now = db.iso()
        done = {s["step"] for s in steps}
        rows = [(owner(s["step"]), group, s["step"], s["status"], s["latency_ms"], s["error"], s["http"],
                 s.get("screenshot"), now, attempt) for s in steps]
        if attempt == 1 and result["failed"]:
            idx = db.ALL_STEPS.index(result["failed_step"])
            rows += [(owner(s), group, s, "skipped", None, f"Not run: blocked by failure at {result['failed_step']}",
                      None, None, now, attempt) for s in db.ALL_STEPS[idx + 1:] if s not in done]
        db.exmany("INSERT INTO runs (journey_id, run_group, step, status, latency_ms, error, http_status, screenshot, ts,"
                  " attempt) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        tag = "FAIL" if result["failed"] else "OK"
        events.emit("crit" if result["failed"] else "ok", "PROBE",
                    f"{journey['name']} attempt {attempt}: {tag}" +
                    (f" at {result['failed_step']} – {result['error']}" if result["failed"] else
                     f" ({sum(s['latency_ms'] for s in steps)} ms e2e)"))
        return result

    def _synthetic_txn(self, amount, bank, status):
        db.insert("transactions", txn_ref="SYN" + uuid.uuid4().hex[:10].upper(), customer_id="PROBE", amount=amount,
                  receiver_bank=bank, status=status, failure_layer=None, error_code=None, ts=db.iso(), synthetic=1)


PROBER = Prober()
