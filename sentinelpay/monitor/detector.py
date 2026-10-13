"""Detection rules: confirmed failures, slow steps, intermittent failures, early warning, dedupe, MTTD."""
from common import config, db
from monitor import alerts, events, rca, recovery

PAYMENT_STEPS = {"submit_transfer", "gateway_pay", "verify_receipt"}
SEVERITY_RANK = {"warning": 0, "major": 1, "critical": 2}
GATEWAY_CAUSES = {"Payment gateway unavailable", "Payment gateway timeout", "Intermittent payment gateway failures"}
INTERMITTENT = "Intermittent payment gateway failures"


def _secs(a, b):
    if not a or not b:
        return None
    return max(0, int((db.parse(b) - db.parse(a)).total_seconds()))


def open_for(journey_id, step):
    return db.q1("SELECT * FROM incidents WHERE journey_id=? AND failed_step=? AND status IN ('open','recovering')"
                 " ORDER BY id DESC LIMIT 1", (journey_id, step))


def last_resolved_at(journey_id, step):
    r = db.q1("SELECT MAX(resolved_at) AS t FROM incidents WHERE journey_id=? AND failed_step=? AND status='resolved'",
              (journey_id, step))
    return (r or {}).get("t") or "1970-01-01T00:00:00Z"


def failure_start(journey_id, step, chaos):
    """First failing run of the current streak; chaos activation time if it is earlier (gives true MTTD)."""
    rows = db.q("SELECT status, ts FROM runs WHERE journey_id=? AND step=? AND status IN ('pass','slow','fail')"
                " ORDER BY id DESC LIMIT 300", (journey_id, step))
    start = None
    for r in rows:
        if r["status"] != "fail":
            break
        start = r["ts"]
    start = start or db.iso()
    act = (chaos or {}).get("activated_at")
    if act and act <= start:
        return act
    return start


def raise_incident(journey_id, step, cause, severity, error=None, http=None, screenshot=None, run_group=None,
                   started=None):
    now = db.iso()
    layer = rca.cause_info(cause)[0]
    existing = open_for(journey_id, step)
    if existing:
        upd = {"last_seen": now}
        if SEVERITY_RANK[severity] > SEVERITY_RANK.get(existing["severity"], 0) and existing["status"] == "open":
            upd.update(severity=severity, cause=cause, layer=layer, error=error, http_status=http)
            if screenshot:
                upd.update(screenshot=screenshot, run_group=run_group)
            db.update("incidents", existing["id"], **upd)
            rca.analyse(existing["id"])
            alerts.send("incident", f"Incident #{existing['id']} escalated to {severity}",
                        f"{cause} on step {step}", existing["id"], slack_text=alerts.incident_text(
                            db.q1("SELECT * FROM incidents WHERE id=?", (existing["id"],))))
            alerts.draft_notice(existing["id"])
        else:
            db.update("incidents", existing["id"], **upd)
        return existing["id"]

    family = GATEWAY_CAUSES if cause in GATEWAY_CAUSES else {cause}

    # Same root cause already open on another journey: one incident per root cause, not per journey.
    same = next((p for p in db.q("SELECT * FROM incidents WHERE status IN ('open','recovering')"
                                 " AND failed_step != 'real transactions' ORDER BY id DESC") if p["cause"] in family), None)
    if same and severity != "warning":
        db.update("incidents", same["id"], last_seen=now)
        j = db.q1("SELECT name FROM journeys WHERE id=?", (journey_id,)) or {"name": "?"}
        events.emit("info", "DEDUPE", f"'{j['name']}' {step} failure ({cause}) folded into incident #{same['id']}")
        return same["id"]

    # A real-transaction pattern may already have opened an incident for this cause: attach probe evidence.
    pat = next((p for p in db.q("SELECT * FROM incidents WHERE failed_step='real transactions'"
                                " AND status IN ('open','recovering') ORDER BY id DESC") if p["cause"] in family), None)
    if pat and severity != "warning":
        sev = severity if SEVERITY_RANK[severity] > SEVERITY_RANK.get(pat["severity"], 0) else pat["severity"]
        db.update("incidents", pat["id"], journey_id=journey_id, failed_step=step, severity=sev, error=error,
                  http_status=http, screenshot=screenshot, run_group=run_group, last_seen=now, cause=cause, layer=layer)
        rca.analyse(pat["id"])
        events.emit("crit", "PROBE", f"Synthetic probe confirmed pattern incident #{pat['id']} on step {step}")
        return pat["id"]

    started = started or now
    iid = db.insert("incidents", journey_id=journey_id, severity=severity, status="open", failed_step=step,
                    layer=layer, cause=cause, error=error, http_status=http, screenshot=screenshot,
                    run_group=run_group, failure_started_at=started, detected_at=now, last_seen=now,
                    mttd_sec=_secs(started, now))
    rca.analyse(iid)
    from monitor import patterns
    patterns.refresh_impact(iid)
    alerts.incident_alert(iid)
    alerts.draft_notice(iid)
    return iid


# ------------------------------------------------------------------ per-flow evaluation

def evaluate(journey, attempts, chaos, owner):
    """attempts: list of flow results for one journey (primary first, then retries).
    owner(step) -> journey_id the step's runs/incidents belong to."""
    primary = attempts[0]
    if primary["failed"]:
        step = primary["failed_step"]
        fails = sum(1 for a in attempts if a["failed"])
        if fails >= 2:
            cause = rca.classify(step, primary["http"], primary["error"], rca.recent_logs(60))
            if cause in GATEWAY_CAUSES and any(not a["failed"] for a in attempts):
                cause = INTERMITTENT
            severity = "critical" if step in PAYMENT_STEPS else "major"
            jid = owner(step)
            raise_incident(jid, step, cause, severity, primary["error"], primary["http"], primary["screenshot"],
                           primary["group"], failure_start(jid, step, chaos))
        else:
            events.emit("warn", "FALSE_ALARM_GUARD",
                        f"{journey['name']}: {step} failed once but retry passed – not raised (1 of {len(attempts)} attempts failed)")
    for s in primary["steps"]:
        if s["status"] in ("pass", "slow", "fail"):
            jid = owner(s["step"])
            check_early_warning(jid, s["step"], chaos)
            check_slow(jid, s["step"], chaos)
            check_intermittent(jid, s["step"], chaos)


def _latency_cause(step):
    return "Payment gateway latency rising" if step == "gateway_pay" else "Bank server latency rising"


def check_early_warning(jid, step, chaos):
    rows = db.q("SELECT latency_ms, ts FROM runs WHERE journey_id=? AND step=? AND attempt=1 AND status IN ('pass','slow')"
                " ORDER BY id DESC LIMIT 3", (jid, step))
    if len(rows) < 3:
        return
    lat = [r["latency_ms"] for r in reversed(rows)]
    if lat[0] < lat[1] < lat[2] and lat[2] > config.EARLY_WARNING_RATIO * config.SLOW_THRESHOLD_MS:
        if open_for(jid, step):
            return
        limit = config.EARLY_WARNING_RATIO * config.SLOW_THRESHOLD_MS
        started = next(r["ts"] for r in reversed(rows) if r["latency_ms"] > limit)
        act = (chaos or {}).get("activated_at")
        if act and act <= started:
            started = act
        raise_incident(jid, step, _latency_cause(step), "warning",
                       error=f"Latency rising {lat[0]} → {lat[1]} → {lat[2]} ms (slow threshold {config.SLOW_THRESHOLD_MS} ms)",
                       started=started)
        events.emit("warn", "EARLY_WARNING", f"Latency on {step} rising for 3 runs: {lat} ms")


def check_slow(jid, step, chaos):
    rows = db.q("SELECT status, latency_ms, ts FROM runs WHERE journey_id=? AND step=? AND attempt=1"
                " AND status IN ('pass','slow','fail') AND ts > ? ORDER BY id DESC LIMIT 3",
                (jid, step, last_resolved_at(jid, step)))
    slow = [r for r in rows if r["status"] == "slow"]
    if len(slow) >= 2:
        started = (chaos or {}).get("activated_at") or rows[-1]["ts"]
        raise_incident(jid, step, _latency_cause(step), "major",
                       error=f"Step slower than {config.SLOW_THRESHOLD_MS} ms in {len(slow)} of last {len(rows)} runs "
                             f"(latest {rows[0]['latency_ms']} ms)", started=started)


def check_intermittent(jid, step, chaos):
    rows = db.q("SELECT status, error, http_status, ts, screenshot, run_group FROM runs WHERE journey_id=? AND step=?"
                " AND status IN ('pass','slow','fail') AND ts > ? AND ts > ? ORDER BY id DESC LIMIT 5",
                (jid, step, last_resolved_at(jid, step), db.ago(minutes=10)))
    fails = [r for r in rows if r["status"] == "fail"]
    chrono = [r["status"] for r in reversed(rows)]
    flapping = any(a == "fail" and b != "fail" for a, b in zip(chrono, chrono[1:]))  # failed, then passed again
    if len(fails) >= 2 and flapping and not open_for(jid, step):
        base = rca.classify(step, fails[0]["http_status"], fails[0]["error"])
        cause = INTERMITTENT if base in GATEWAY_CAUSES else base
        shot = next((f["screenshot"] for f in fails if f["screenshot"]), None)
        raise_incident(jid, step, cause, "major",
                       error=f"{len(fails)} of last {len(rows)} runs failed (latest run {rows[0]['status']}): {fails[0]['error']}",
                       http=fails[0]["http_status"], screenshot=shot, run_group=fails[0]["run_group"],
                       started=fails[-1]["ts"])
        events.emit("crit", "INTERMITTENT", f"{step}: {len(fails)}/{len(rows)} recent runs failed")


# ------------------------------------------------------------------ cycle level

def after_cycle(cycle):
    recovery.verify_recovering(cycle)
    for inc in db.q("SELECT * FROM incidents WHERE status='open' AND failed_step != 'real transactions'"):
        runs = db.q("SELECT status, latency_ms FROM runs WHERE journey_id=? AND step=? AND ts > ?"
                    " AND status IN ('pass','slow','fail') ORDER BY id DESC LIMIT 10",
                    (inc["journey_id"], inc["failed_step"], inc["detected_at"]))
        # Gateway failures that turn out to be mixed with passes are re-labelled as intermittent.
        chrono = [r["status"] for r in reversed(runs)]
        pass_then_fail = any(a != "fail" and b == "fail" for a, b in zip(chrono, chrono[1:]))
        if inc["cause"] == "Payment gateway unavailable" and pass_then_fail:
            db.update("incidents", inc["id"], cause=INTERMITTENT)
            rca.analyse(inc["id"])
            events.emit("info", "RCA", f"Incident #{inc['id']} re-classified as intermittent gateway failures")
            continue
        # Auto-close when the condition clears on its own (no recovery action is run).
        need = 10 if inc["cause"] == INTERMITTENT else 3
        clean = [r for r in runs[:need] if r["status"] == "pass" and
                 (inc["severity"] != "warning" or r["latency_ms"] < config.EARLY_WARNING_RATIO * config.SLOW_THRESHOLD_MS)]
        if len(runs) >= need and len(clean) == need:
            recovery.resolve(inc["id"], "Condition cleared without a recovery action (auto-closed)", None,
                             count_mttr=False)


def on_bank_unreachable(streak, error, login_journey_id, started):
    if streak < 3:
        events.emit("warn", "PROBE_NET",
                    f"Bank unreachable ({streak}/3): treated as probe/network error, no incident raised yet")
        return
    raise_incident(login_journey_id, "login", "Bank application unreachable", "critical",
                   error=f"Bank health check failed {streak} times in a row: {error}", started=started)


def on_bank_reachable():
    for inc in db.q("SELECT * FROM incidents WHERE cause='Bank application unreachable' AND status IN ('open','recovering')"):
        recovery.resolve(inc["id"], "Bank application reachable again", True if inc["status"] == "recovering" else None,
                         count_mttr=inc["status"] == "recovering")
