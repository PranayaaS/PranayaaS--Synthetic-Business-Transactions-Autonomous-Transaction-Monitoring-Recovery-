"""Root-cause analysis: layer classification, similar incidents, fix catalogue, optional Gemini."""
import threading

import httpx

from common import config, db
from monitor import events

LAYER_LABEL = {
    "gateway": "Payment gateway",
    "server": "Bank server",
    "receiver_bank": "Receiver bank",
    "customer_network": "Customer network",
}

FIXES = {
    "switch_backup_gateway": {"label": "Switch to backup gateway", "manual": False},
    "restart_payment_service": {"label": "Restart payment service", "manual": False},
    "rollback_receipt_service": {"label": "Rollback receipt service", "manual": False},
    "pause_receiver_bank": {"label": "Pause transfers to receiver bank + notify customers", "manual": False},
    "review_limit_rule": {"label": "Review limit/risk rule with operations", "manual": True,
                          "optional": "restart_payment_service"},
}

# cause text -> (layer, cause key used for fix learning, suggested fix, plain-English explanation)
CAUSES = {
    "Probe network issue – ignored": ("customer_network", "probe", None,
                                      "The monitoring probe itself lost connectivity, so the result was ignored."),
    "Payment gateway unavailable": ("gateway", "gateway", "switch_backup_gateway",
                                    "The payment gateway is rejecting payment requests with HTTP 502, so customers' transfers fail before reaching the receiver bank."),
    "Payment gateway timeout": ("gateway", "gateway", "switch_backup_gateway",
                                "The payment gateway is accepting requests but not answering in time. Customers may be debited without the credit going through, which feeds the RBI reversal watchdog."),
    "Intermittent payment gateway failures": ("gateway", "gateway", "switch_backup_gateway",
                                              "Some payment requests succeed and others get HTTP 502 from the gateway. This is the early stage of a gateway problem and causes repeat attempts and complaints."),
    "Payment gateway latency rising": ("gateway", "gateway", "switch_backup_gateway",
                                       "Payment gateway response time has risen for several consecutive checks and is close to the slow threshold. Failures are likely if the trend continues."),
    "Bank server latency rising": ("server", "server_error", "restart_payment_service",
                                   "Bank application response time has risen for several consecutive checks and is close to the slow threshold."),
    "Bank application server error": ("server", "server_error", "restart_payment_service",
                                      "The bank's own application server is returning HTTP 500 on login, so customers cannot start any payment journey."),
    "Bank application unreachable": ("server", "server_error", "restart_payment_service",
                                     "The bank application did not answer the probe's health check three times in a row; the service appears to be down."),
    "Data integrity error in payment confirmation": ("server", "data_integrity", "rollback_receipt_service",
                                                     "Payments go through but the confirmation shows a different amount from what the customer paid. This is a data integrity defect in the receipt service."),
    "Receiver bank not responding": ("receiver_bank", "receiver_bank", "pause_receiver_bank",
                                     "Our systems are healthy, but the receiving bank is not responding (RB_UNAVAILABLE). Only transfers to that bank fail."),
    "High-value transfers blocked by limit/risk rule": ("server", "limit_risk", "review_limit_rule",
                                                        "Transfers above Rs 50,000 are being rejected by a limit or fraud-risk rule (LIMIT_OR_RISK_CHECK). Smaller transfers are unaffected."),
}

# Error codes in real transactions that belong to each cause (used for pattern -> cause and impact).
CAUSE_CODES = {
    "Payment gateway unavailable": None, "Payment gateway timeout": None,
    "Intermittent payment gateway failures": None, "Payment gateway latency rising": None,
    "Receiver bank not responding": ("RB_UNAVAILABLE",),
    "High-value transfers blocked by limit/risk rule": ("LIMIT_OR_RISK_CHECK",),
    "Data integrity error in payment confirmation": ("NO_MATCH",),
    "Bank application server error": ("NO_MATCH",), "Bank application unreachable": ("NO_MATCH",),
}

CODE_CAUSE = {
    "GW_UNAVAILABLE": "Payment gateway unavailable",
    "GW_TIMEOUT": "Payment gateway timeout",
    "RB_UNAVAILABLE": "Receiver bank not responding",
    "LIMIT_OR_RISK_CHECK": "High-value transfers blocked by limit/risk rule",
}


def cause_info(cause):
    return CAUSES.get(cause, ("server", "other", "restart_payment_service", "Unclassified failure."))


def classify(step, http_status, error, logs=None):
    """Rule-based classification from failed step, HTTP status, error text and bank logs."""
    e = (error or "").lower()
    if "unreachable" in e:
        return "Bank application unreachable"
    if "rb_unavailable" in e or http_status == 503:
        return "Receiver bank not responding"
    if "limit_or_risk_check" in e or http_status == 422:
        return "High-value transfers blocked by limit/risk rule"
    if step == "login" and (http_status == 500 or "500" in e):
        return "Bank application server error"
    if step == "verify_receipt" and ("mismatch" in e or "amount" in e):
        return "Data integrity error in payment confirmation"
    if step == "gateway_pay":
        if http_status == 502 or "502" in e:
            return "Payment gateway unavailable"
        if "timeout" in e:
            return "Payment gateway timeout"
    # Fall back to the dominant layer hint in the bank's logs for the failure window.
    hints = [l["layer_hint"] for l in (logs or []) if l.get("layer_hint") not in (None, "none")]
    if hints:
        top = max(set(hints), key=hints.count)
        return {"gateway": "Payment gateway unavailable", "receiver_bank": "Receiver bank not responding"}.get(
            top, "Bank application server error")
    return "Bank application server error"


def recent_logs(seconds=60, limit=40):
    return db.q("SELECT * FROM bank_logs WHERE ts >= ? ORDER BY id DESC LIMIT ?",
                (db.ago(seconds=seconds), limit))


def fix_stats(cause_key, fix):
    r = db.q1("SELECT COUNT(*) AS total, COALESCE(SUM(success),0) AS worked FROM fix_history WHERE cause=? AND fix=?",
              (cause_key, fix))
    return int(r["worked"]), int(r["total"])


def fix_summary(cause):
    """Suggested fix with learned success history."""
    _, key, fix, _ = cause_info(cause)
    if not fix:
        return None
    meta = FIXES[fix]
    out = {"action": fix, "label": meta["label"], "manual": meta["manual"]}
    target = meta.get("optional", fix)
    worked, total = fix_stats(key, target)
    out.update(worked=worked, total=total,
               history_text=f"Worked {worked} of {total} times" if total else "No history yet")
    if meta.get("optional"):
        opt = meta["optional"]
        out["optional"] = {"action": opt, "label": FIXES[opt]["label"], "worked": worked, "total": total}
    # All fixes tried for this cause, for the learning panel.
    out["history"] = [
        {"fix": r["fix"], "label": FIXES.get(r["fix"], {}).get("label", r["fix"]), "worked": int(r["worked"]),
         "total": int(r["total"])}
        for r in db.q("SELECT fix, COUNT(*) AS total, SUM(success) AS worked FROM fix_history WHERE cause=? GROUP BY fix",
                      (key,))
    ]
    return out


def similar_incident(cause, exclude_id=None):
    row = db.q1("SELECT * FROM incidents WHERE cause=? AND status='resolved' AND recovery_action IS NOT NULL AND id != ?"
                " ORDER BY resolved_at DESC LIMIT 1", (cause, exclude_id or -1))
    if not row:
        return None
    mins = round((row["mttr_sec"] or 0) / 60, 1)
    fix = FIXES.get(row["recovery_action"], {}).get("label", row["recovery_action"])
    return {"id": row["id"], "mttr_sec": row["mttr_sec"], "fix": fix,
            "text": f"Similar to Incident #{row['id']} (resolved in {mins} min with: {fix})"}


def analyse(incident_id):
    """Fill similar incident + suggested fix, then ask Gemini in the background if configured."""
    inc = db.q1("SELECT * FROM incidents WHERE id=?", (incident_id,))
    if not inc:
        return
    sim = similar_incident(inc["cause"], incident_id)
    _, _, fix, _ = cause_info(inc["cause"])
    db.update("incidents", incident_id, similar_incident_id=sim["id"] if sim else None, suggested_fix=fix,
              layer=cause_info(inc["cause"])[0])
    if config.GEMINI_API_KEY:
        threading.Thread(target=_gemini, args=(incident_id,), daemon=True).start()


def _gemini(incident_id):
    inc = db.q1("SELECT * FROM incidents WHERE id=?", (incident_id,))
    logs = recent_logs(120, 20)
    log_text = "\n".join(f"{l['ts']} {l['method']} {l['endpoint']} {l['http_status']} {l['duration_ms']}ms "
                         f"layer={l['layer_hint']} {l['message'] or ''}" for l in reversed(logs))
    prompt = (f"You are helping a cooperative bank's operations manager. A synthetic payment probe found this failure.\n"
              f"Failed step: {inc['failed_step']}\nDetected cause: {inc['cause']}\nLayer: {inc['layer']}\n"
              f"Error: {inc['error']}\nLast bank log lines:\n{log_text}\n\n"
              "Explain in exactly 2 plain-English sentences what is going wrong and what it means for customers.")
    try:
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent",
                       headers={"x-goog-api-key": config.GEMINI_API_KEY},
                       json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=8)
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        db.update("incidents", incident_id, ai_explanation=text)
        events.emit("info", "AI_RCA", f"Gemini explanation added to incident #{incident_id}")
    except Exception:
        pass  # optional feature: fail silently
