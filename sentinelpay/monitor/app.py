"""SentinelPay monitor (port 8000): background engine, JSON API and dashboard pages."""
import json
import threading
from datetime import timedelta
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from common import config, db, http
from monitor import alerts, events, patterns, rca, recovery, simulator, watchdog
from monitor.probe import PROBER
from monitor.reports import build_report

STATIC = Path(__file__).parent / "static"


# ------------------------------------------------------------------ background engine

def engine_loop():
    last = {"sim": 0, "pat": 0, "wd": 0}
    while True:
        now = time.time()
        for key, every, fn in (("sim", 2, simulator.tick), ("pat", 10, patterns.tick), ("wd", 15, watchdog.tick)):
            if now - last[key] >= every:
                last[key] = now
                try:
                    fn()
                except Exception:
                    traceback.print_exc()
        time.sleep(0.5)


@asynccontextmanager
async def lifespan(app):
    db.init_schema()
    db.seed_if_empty()
    threading.Thread(target=engine_loop, name="engine", daemon=True).start()
    PROBER.start()
    events.emit("info", "SYS_INIT", "SentinelPay engine started: simulator, pattern engine, RBI watchdog, probes")
    yield


app = FastAPI(title="SentinelPay – Transaction Health Engine", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8001", "http://127.0.0.1:8001"],
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.mount("/screenshots", StaticFiles(directory=str(config.SHOT_DIR)), name="screenshots")


# ------------------------------------------------------------------ pages

PAGES = {"/": "overview.html", "/incidents": "incidents.html", "/incident": "incident.html",
         "/chaos": "chaos.html", "/tests": "tests.html", "/watchdog": "watchdog.html"}


def _page(name):
    return lambda: FileResponse(STATIC / name, headers={"Cache-Control": "no-store"})


for _path, _file in PAGES.items():
    app.add_api_route(_path, _page(_file), methods=["GET"], include_in_schema=False)


# ------------------------------------------------------------------ helpers

def _journey_map():
    return {j["id"]: j for j in db.q("SELECT * FROM journeys")}


def _pass_rate(journey_id, hours=24):
    rows = db.q("SELECT run_group, MAX(CASE WHEN status='fail' THEN 1 ELSE 0 END) AS f FROM runs WHERE journey_id=?"
                " AND attempt=1 AND ts>=? AND status IN ('pass','slow','fail') GROUP BY run_group",
                (journey_id, db.ago(hours=hours)))
    if not rows:
        return None
    return round(100 * (1 - sum(r["f"] for r in rows) / len(rows)), 1)


def _journey_health(j, open_incs):
    steps = []
    for s in db.journey_steps(j):
        r = db.q1("SELECT status, latency_ms, ts, error FROM runs WHERE journey_id=? AND step=? AND attempt=1"
                  " AND status != 'probe_error' ORDER BY id DESC LIMIT 1", (j["id"], s))
        steps.append({"step": s, **(r or {"status": None, "latency_ms": None, "ts": None, "error": None})})
    incs = [i for i in open_incs if i["journey_id"] == j["id"]]
    statuses = {s["status"] for s in steps}
    if any(i["severity"] in ("critical", "major") for i in incs) or "fail" in statuses:
        health = "red"
    elif incs or statuses & {"slow", "skipped"}:
        health = "amber"
    else:
        health = "green"
    last = max((s["ts"] for s in steps if s["ts"]), default=None)
    return {**j, "health": health, "steps": steps, "last_run": last, "pass_rate": _pass_rate(j["id"]),
            "e2e_ms": sum(s["latency_ms"] or 0 for s in steps if s["status"] in ("pass", "slow")),
            "open_incident": incs[0] if incs else None}


def _incident_row(i, jmap):
    j = jmap.get(i["journey_id"]) or {}
    return {**i, "journey": j.get("name", "Real transactions"), "journey_auto": j.get("auto_created", 0),
            "layer_label": rca.LAYER_LABEL.get(i["layer"], i["layer"]),
            "fix": rca.fix_summary(i["cause"]) if i["status"] != "resolved" else None,
            "screenshot_url": f"/screenshots/{i['screenshot']}" if i["screenshot"] else None}


def _bank(method, path, timeout=5):
    try:
        r = http.client().request(method, f"{config.BANK_URL}{path}", timeout=timeout)
        return r.json()
    except Exception as e:
        raise HTTPException(502, f"Mock bank unreachable: {e}")


# ------------------------------------------------------------------ API

@app.get("/api/ping")
def ping():
    return {"ok": True}


@app.get("/api/status")
def status():
    jmap = _journey_map()
    open_incs = db.q("SELECT * FROM incidents WHERE status IN ('open','recovering') ORDER BY id DESC")
    journeys = [_journey_health(j, open_incs) for j in jmap.values() if j["active"]]
    journeys.sort(key=lambda j: (j["auto_created"], j["id"]))
    core = [j for j in journeys if not j["auto_created"]]
    mttd = db.q1("SELECT AVG(mttd_sec) AS a, COUNT(mttd_sec) AS n FROM incidents WHERE mttd_sec IS NOT NULL")
    mttr = db.q1("SELECT AVG(mttr_sec) AS a, COUNT(mttr_sec) AS n FROM incidents WHERE mttr_sec IS NOT NULL")
    hb = db.q1("SELECT COUNT(*) AS n, SUM(CASE WHEN status IN ('pass','slow') THEN 1 ELSE 0 END) AS ok FROM runs"
               " WHERE ts >= ? AND status != 'skipped'", (db.ago(hours=1),))
    tx = db.q1("SELECT COUNT(*) AS n, SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS ok FROM transactions"
               " WHERE synthetic=0 AND ts >= ?", (db.ago(minutes=5),))
    tps = db.q1("SELECT COUNT(*) AS n FROM transactions WHERE synthetic=0 AND ts >= ?", (db.ago(seconds=60),))["n"] / 60
    dnc = db.q1("SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS v FROM transactions WHERE status='debited_not_credited'")
    nxt = PROBER.next_cycle_at
    return {
        "journeys": journeys,
        "kpis": {
            "journeys_healthy": sum(1 for j in journeys if j["health"] == "green"),
            "journeys_total": len(journeys),
            "core_healthy": sum(1 for j in core if j["health"] == "green"), "core_total": len(core),
            "mttd_avg_sec": round(mttd["a"]) if mttd["a"] is not None else None, "mttd_n": mttd["n"],
            "mttr_avg_sec": round(mttr["a"]) if mttr["a"] is not None else None, "mttr_n": mttr["n"],
            "open_incidents": len(open_incs),
            "critical_open": sum(1 for i in open_incs if i["severity"] == "critical"),
            "warning_open": sum(1 for i in open_incs if i["severity"] == "warning"),
            "impact_amount": sum(i["impact_amount"] or 0 for i in open_incs),
            "impact_customers": sum(i["impact_customers"] or 0 for i in open_incs),
            "pending_reversals": dnc["n"], "pending_reversal_value": dnc["v"],
        },
        "top_incident": _incident_row(open_incs[0], jmap) if open_incs else None,
        "probe": {"status": PROBER.status, "running": PROBER.running, "last_cycle_at": PROBER.last_cycle_at,
                  "next_cycle_in": max(0, round(nxt - time.time())) if nxt else None,
                  "interval_sec": config.PROBE_INTERVAL_SEC, "cycles": PROBER.cycles,
                  "bank_unreachable_streak": PROBER.unreachable_streak,
                  "heartbeat_ok": hb["ok"] or 0, "heartbeat_total": hb["n"] or 0},
        "traffic": {"tps": round(tps, 2), "success_rate": round(100 * (tx["ok"] or 0) / tx["n"], 2) if tx["n"] else None,
                    "txns_5m": tx["n"]},
        "chaos": simulator.CHAOS["state"], "bank_reachable": simulator.CHAOS["reachable"],
        "config": {"slow_threshold_ms": config.SLOW_THRESHOLD_MS, "slack": bool(config.SLACK_WEBHOOK_URL),
                   "gemini": bool(config.GEMINI_API_KEY), "demo_mode": config.DEMO_MODE},
        "server_time": db.iso(),
    }


@app.get("/api/latency")
def latency(minutes: int = 30, journey_id: int = None):
    if journey_id:
        ids = [journey_id]
    else:
        ids = [j["id"] for j in db.q("SELECT id FROM journeys WHERE auto_created=0")]
    marks = ",".join("?" * len(ids))
    rows = db.q(f"SELECT run_group, step, latency_ms, status, ts FROM runs WHERE ts >= ? AND attempt=1 AND journey_id IN ({marks})"
                " AND status IN ('pass','slow','fail') ORDER BY id", (db.ago(minutes=minutes), *ids))
    groups, order = {}, []
    for r in rows:
        if r["run_group"] not in groups:
            groups[r["run_group"]] = {"ts": r["ts"]}
            order.append(r["run_group"])
        groups[r["run_group"]][r["step"]] = r["latency_ms"]
        if r["status"] == "fail":
            groups[r["run_group"]]["fail"] = r["step"]
    labels = [groups[g]["ts"] for g in order]
    series = {s: [groups[g].get(s) for g in order] for s in db.ALL_STEPS}
    fails = [groups[g].get("fail") for g in order]
    e2e = [sum(v for k, v in groups[g].items() if k in db.ALL_STEPS and v) for g in order]
    lat_vals = sorted(v for s in series.values() for v in s if v)
    return {"labels": labels, "series": series, "failures": fails, "e2e": e2e,
            "threshold_ms": config.SLOW_THRESHOLD_MS,
            "avg_ms": round(sum(e2e) / len(e2e)) if e2e else None,
            "p99_ms": lat_vals[int(len(lat_vals) * 0.99) - 1] if lat_vals else None}


@app.get("/api/layers")
def layers(minutes: int = 60):
    out = {}
    open_incs = db.q("SELECT layer, severity FROM incidents WHERE status IN ('open','recovering')")
    total = db.q1("SELECT COUNT(*) AS n FROM transactions WHERE synthetic=0 AND ts >= ?", (db.ago(minutes=minutes),))["n"]
    for layer in ("customer_network", "server", "gateway", "receiver_bank"):
        n = db.q1("SELECT COUNT(*) AS n FROM transactions WHERE synthetic=0 AND failure_layer=? AND ts >= ?"
                  " AND status IN ('failed','debited_not_credited')", (layer, db.ago(minutes=minutes)))["n"]
        n5 = db.q1("SELECT COUNT(*) AS n FROM transactions WHERE synthetic=0 AND failure_layer=? AND ts >= ?"
                   " AND status IN ('failed','debited_not_credited')", (layer, db.ago(minutes=5)))["n"]
        sev = [i["severity"] for i in open_incs if i["layer"] == layer]
        state = "critical" if any(s in ("critical", "major") for s in sev) else "elevated" if sev or n5 >= 3 else "nominal"
        out[layer] = {"label": rca.LAYER_LABEL[layer], "failures": n, "failures_5m": n5, "state": state,
                      "rate": round(100 * n / total, 2) if total else 0}
    return {"minutes": minutes, "total_txns": total, "layers": out}


@app.get("/api/incidents")
def incidents(status: str = "", limit: int = 100):
    jmap = _journey_map()
    if status:
        sts = [s for s in status.split(",") if s]
        rows = db.q(f"SELECT * FROM incidents WHERE status IN ({','.join('?' * len(sts))}) ORDER BY id DESC LIMIT ?",
                    (*sts, limit))
    else:
        rows = db.q("SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (limit,))
    return [_incident_row(i, jmap) for i in rows]


@app.get("/api/incidents/{iid}")
def incident(iid: int):
    i = db.q1("SELECT * FROM incidents WHERE id=?", (iid,))
    if not i:
        raise HTTPException(404, "Incident not found")
    row = _incident_row(i, _journey_map())
    row["fix"] = rca.fix_summary(i["cause"])
    row["explanation"] = i["ai_explanation"] or rca.cause_info(i["cause"])[3]
    row["explanation_source"] = "Gemini" if i["ai_explanation"] else "Rule-based RCA"
    row["similar"] = rca.similar_incident(i["cause"], iid)
    row["timeline"] = [
        {"key": "failure_started", "label": "Failure started", "ts": i["failure_started_at"]},
        {"key": "detected", "label": "Detected", "ts": i["detected_at"]},
        {"key": "alerted", "label": "Alerted", "ts": i["alerted_at"]},
        {"key": "approved", "label": "Approved", "ts": i["approved_at"], "by": i["approved_by"]},
        {"key": "resolved", "label": "Resolved", "ts": i["resolved_at"], "note": i["resolution_note"]},
    ]
    row["waterfall"] = db.q("SELECT step, status, latency_ms, error, http_status FROM runs WHERE run_group=? ORDER BY id",
                            (i["run_group"],)) if i["run_group"] else []
    start = db.iso(db.parse(i["failure_started_at"] or i["detected_at"]) - timedelta(seconds=30))
    row["logs"] = db.q("SELECT * FROM bank_logs WHERE ts >= ? AND ts <= ? ORDER BY id DESC LIMIT 25",
                       (start, i["resolved_at"] or i["last_seen"] or i["detected_at"]))
    if not row["logs"]:
        row["logs"] = db.q("SELECT * FROM bank_logs WHERE ts <= ? ORDER BY id DESC LIMIT 15",
                           (i["last_seen"] or i["detected_at"],))
    row["notices"] = db.q("SELECT * FROM notices WHERE incident_id=? ORDER BY id DESC", (iid,))
    # Real-transaction failures per minute for this layer around the incident.
    end = db.parse(i["resolved_at"]) if i["resolved_at"] else db.utcnow()
    buckets = []
    for k in range(10, 0, -1):
        a, b = end - timedelta(minutes=k), end - timedelta(minutes=k - 1)
        n = db.q1("SELECT COUNT(*) AS n FROM transactions WHERE synthetic=0 AND failure_layer=? AND ts>=? AND ts<?"
                  " AND status IN ('failed','debited_not_credited')", (i["layer"], db.iso(a), db.iso(b)))["n"]
        buckets.append({"t": db.iso(b), "n": n})
    row["failure_series"] = buckets
    stats = db.q1("SELECT COUNT(*) AS n, AVG(amount) AS avg, MAX(amount) AS mx FROM transactions WHERE synthetic=0"
                  " AND failure_layer=? AND ts >= ? AND ts <= ? AND status IN ('failed','debited_not_credited')",
                  (i["layer"], i["failure_started_at"] or i["detected_at"], i["resolved_at"] or db.iso()))
    row["pattern_stats"] = {"failed": stats["n"], "avg_ticket": round(stats["avg"] or 0), "max_ticket": stats["mx"] or 0}
    return row


@app.post("/api/incidents/{iid}/approve")
def approve(iid: int, payload: dict = Body(default={})):
    ok, msg = recovery.approve(iid, (payload or {}).get("approved_by") or "Ops Manager", (payload or {}).get("action"))
    if not ok:
        return JSONResponse({"ok": False, "message": msg}, status_code=409)
    return {"ok": True, "message": msg}


@app.post("/api/incidents/{iid}/dismiss")
def dismiss(iid: int, payload: dict = Body(default={})):
    ok, msg = recovery.dismiss(iid, (payload or {}).get("by") or "Ops Manager")
    if not ok:
        return JSONResponse({"ok": False, "message": msg}, status_code=409)
    return {"ok": True, "message": msg}


@app.post("/api/incidents/{iid}/realert")
def realert(iid: int):
    if not db.q1("SELECT id FROM incidents WHERE id=?", (iid,)):
        raise HTTPException(404, "Incident not found")
    alerts.incident_alert(iid)
    return {"ok": True, "channel": "slack" if config.SLACK_WEBHOOK_URL else "in-app"}


@app.get("/api/incidents/{iid}/report")
def report(iid: int, download: int = 0):
    i = db.q1("SELECT * FROM incidents WHERE id=?", (iid,))
    if not i:
        raise HTTPException(404, "Incident not found")
    md = i["report_md"] or build_report(iid)
    headers = {"Content-Disposition": f'attachment; filename="incident-{iid}-report.md"'} if download else {}
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8", headers=headers)


@app.get("/api/tests")
def tests():
    out = []
    for j in db.q("SELECT * FROM journeys ORDER BY auto_created DESC, id DESC"):
        groups = db.q("SELECT run_group, MIN(ts) AS ts, SUM(COALESCE(latency_ms,0)) AS e2e,"
                      " MAX(CASE WHEN status='fail' THEN 1 ELSE 0 END) AS f FROM runs WHERE journey_id=? AND attempt=1"
                      " AND status IN ('pass','slow','fail') GROUP BY run_group ORDER BY MIN(id) DESC LIMIT 10", (j["id"],))
        last = groups[0] if groups else None
        pat = db.q1("SELECT * FROM patterns WHERE signature=?", (j["created_from_pattern"],)) if j["created_from_pattern"] else None
        out.append({**j, "steps": db.journey_steps(j), "pass_rate": _pass_rate(j["id"]),
                    "last_run": last["ts"] if last else None, "last_status": ("fail" if last["f"] else "pass") if last else None,
                    "last_e2e_ms": last["e2e"] if last else None,
                    "recent": [{"ts": g["ts"], "e2e": g["e2e"], "fail": g["f"]} for g in reversed(groups)],
                    "pattern_summary": pat["summary"] if pat else None,
                    "incidents": db.q1("SELECT COUNT(*) AS n FROM incidents WHERE journey_id=?", (j["id"],))["n"]})
    return {"tests": out, "interval_sec": config.PROBE_INTERVAL_SEC,
            "patterns": db.q("SELECT * FROM patterns ORDER BY id DESC")}


@app.get("/api/tests/export")
def export_tests():
    data = [{k: j[k] for k in ("id", "name", "description", "amount", "receiver_bank", "auto_created",
                                "created_from_pattern", "created_at", "active")} | {"steps": db.journey_steps(j)}
            for j in db.q("SELECT * FROM journeys ORDER BY id")]
    return Response(json.dumps({"exported_at": db.iso(), "journeys": data}, indent=2, ensure_ascii=False),
                    media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="sentinelpay-test-suites.json"'})


@app.patch("/api/journeys/{jid}")
def edit_journey(jid: int, payload: dict = Body(default={})):
    j = db.q1("SELECT * FROM journeys WHERE id=?", (jid,))
    if not j:
        raise HTTPException(404, "Journey not found")
    upd = {}
    if "amount" in payload:
        amt = int(payload["amount"])
        if amt <= 0:
            raise HTTPException(400, "Amount must be positive")
        upd["amount"] = amt
    if "receiver_bank" in payload:
        if payload["receiver_bank"] not in simulator.BANKS:
            raise HTTPException(400, "Unknown bank")
        upd["receiver_bank"] = payload["receiver_bank"]
    if "active" in payload:
        upd["active"] = 1 if payload["active"] else 0
    if j["auto_created"] == 0 and ("amount" in upd or "receiver_bank" in upd):
        raise HTTPException(400, "Core journeys use the standard ₹500 payment; edit auto-created tests instead")
    db.update("journeys", jid, **upd)
    events.emit("info", "TEST_EDIT", f"Journey '{j['name']}' updated: {upd}")
    return db.q1("SELECT * FROM journeys WHERE id=?", (jid,))


@app.post("/api/journeys/{jid}/run")
def run_journey(jid: int):
    PROBER.run_now()
    return {"ok": True, "message": "Probe cycle queued", "running": PROBER.running}


@app.get("/api/watchdog")
def get_watchdog():
    return watchdog.summary()


@app.post("/api/watchdog/reverse-all")
def wd_reverse_all():
    return {"reversed": watchdog.reverse_all()}


@app.post("/api/watchdog/{txn_id}/reverse")
def wd_reverse(txn_id: int):
    if not watchdog.reverse(txn_id):
        raise HTTPException(404, "Transaction not pending reversal")
    return {"ok": True}


@app.get("/api/alerts")
def get_alerts(since: int = 0, limit: int = 50):
    if since <= 0:
        return db.q("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))
    return db.q("SELECT * FROM alerts WHERE id > ? ORDER BY id ASC LIMIT ?", (since, limit))


@app.get("/api/notices")
def get_notices():
    rows = db.q("SELECT n.*, i.cause, i.status AS incident_status FROM notices n LEFT JOIN incidents i ON i.id=n.incident_id"
                " ORDER BY n.id DESC LIMIT 50")
    return rows


@app.post("/api/notices")
def create_notice(payload: dict = Body(default={})):
    text = (payload or {}).get("text", "").strip()
    if not text:
        raise HTTPException(400, "Notice text required")
    nid = db.insert("notices", incident_id=payload.get("incident_id"), text=text, status="draft", ts=db.iso())
    return db.q1("SELECT * FROM notices WHERE id=?", (nid,))


@app.get("/api/notices/active")
def active_notices():
    return db.q("SELECT id, text, ts FROM notices WHERE status='approved' ORDER BY id DESC")


@app.post("/api/notices/{nid}/approve")
def approve_notice(nid: int, payload: dict = Body(default={})):
    n = db.q1("SELECT * FROM notices WHERE id=?", (nid,))
    if not n:
        raise HTTPException(404, "Notice not found")
    text = ((payload or {}).get("text") or n["text"]).strip()
    db.update("notices", nid, status="approved", text=text)
    alerts.send("notice", "Customer notice published", f"Banner live on the bank site: \"{text}\"", n["incident_id"])
    return {"ok": True}


@app.post("/api/notices/{nid}/dismiss")
def dismiss_notice(nid: int):
    if not db.q1("SELECT id FROM notices WHERE id=?", (nid,)):
        raise HTTPException(404, "Notice not found")
    db.update("notices", nid, status="dismissed")
    return {"ok": True}


@app.get("/api/chaos")
def get_chaos():
    return _bank("GET", "/api/chaos")


@app.post("/api/chaos/{mode}")
def set_chaos(mode: str):
    try:
        r = http.client().post(f"{config.BANK_URL}/api/chaos/{mode}", timeout=5)
    except Exception as e:
        raise HTTPException(502, f"Mock bank unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.json().get("error", "chaos error"))
    simulator.CHAOS["state"] = r.json()
    if mode == "none":
        events.emit("ok", "CHAOS", "All chaos injections reset – bank back to normal behaviour")
    else:
        events.emit("crit", "CHAOS", f"INJECTION ACTIVATED: {mode} – {r.json()['description']}")
    return r.json()


@app.post("/api/probe/run")
def probe_run():
    PROBER.run_now()
    return {"ok": True, "running": PROBER.running}


@app.get("/api/events")
def get_events(since: int = 0):
    return events.since(since)


@app.get("/api/bank-logs")
def bank_logs(limit: int = 30):
    return db.q("SELECT * FROM bank_logs ORDER BY id DESC LIMIT ?", (limit,))
