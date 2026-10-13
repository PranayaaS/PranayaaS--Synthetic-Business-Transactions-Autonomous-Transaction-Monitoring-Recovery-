"""Alerts: always logged in-app (and console); posted to Slack when a webhook is configured."""
import threading

import httpx

from common import config, db
from monitor import events
from monitor.rca import LAYER_LABEL, fix_summary, similar_incident
from monitor.reports import inr


def _post_slack(text):
    try:
        httpx.post(config.SLACK_WEBHOOK_URL, json={"text": text}, timeout=5)
    except Exception as e:
        events.emit("warn", "SLACK", f"Slack post failed: {e}")


def send(kind, title, message, incident_id=None, slack_text=None):
    channel = "slack" if config.SLACK_WEBHOOK_URL else "in-app"
    aid = db.insert("alerts", incident_id=incident_id, channel=channel, message=message, ts=db.iso(),
                    kind=kind, title=title)
    events.emit("crit" if kind == "incident" else "info", "ALERT", f"{title}: {message}")
    if config.SLACK_WEBHOOK_URL:
        threading.Thread(target=_post_slack, args=(slack_text or f"*{title}*\n{message}",), daemon=True).start()
    return aid


def incident_text(inc):
    j = db.q1("SELECT name FROM journeys WHERE id=?", (inc["journey_id"],)) or {"name": "Real transactions"}
    fix = fix_summary(inc["cause"])
    sim = similar_incident(inc["cause"], inc["id"])
    lines = [
        f":rotating_light: [{inc['severity'].upper()}] {j['name']} – step {inc['failed_step']} failed",
        f"Layer: {LAYER_LABEL.get(inc['layer'], inc['layer'])} | Cause: {inc['cause']}",
        f"Impact: {inr(inc['impact_amount'])} · {inc['impact_customers'] or 0} customers",
    ]
    extra = []
    if sim:
        extra.append(f"Similar to Incident #{sim['id']}")
    if fix:
        extra.append(f"Suggested fix: {fix['label']} (worked {fix['worked']}/{fix['total']})")
    if extra:
        lines.append(" · ".join(extra))
    lines.append(f"Approve in dashboard: {config.MONITOR_URL}/incident?id={inc['id']}")
    return "\n".join(lines)


def incident_alert(incident_id):
    inc = db.q1("SELECT * FROM incidents WHERE id=?", (incident_id,))
    text = incident_text(inc)
    send("incident", f"{inc['severity'].capitalize()} incident #{inc['id']}",
         f"{inc['cause']} ({LAYER_LABEL.get(inc['layer'], inc['layer'])}) on step {inc['failed_step']}",
         incident_id, slack_text=text)
    db.update("incidents", incident_id, alerted_at=db.iso())


# ------------------------------------------------------------------ customer notices

def draft_notice(incident_id):
    inc = db.q1("SELECT * FROM incidents WHERE id=?", (incident_id,))
    if not inc or inc["layer"] not in ("gateway", "receiver_bank"):
        return None
    if db.q1("SELECT id FROM notices WHERE incident_id=? AND status IN ('draft','approved')", (incident_id,)):
        return None
    if inc["layer"] == "receiver_bank":
        bank = "Bank X"
        sig = inc["pattern_signature"] or ""
        if sig.count("|") == 2 and sig.split("|")[1] != "ANY":
            bank = sig.split("|")[1]
        text = f"UPI transfers to {bank} are temporarily delayed. Your money is safe; please retry after some time."
    else:
        text = ("UPI and fund transfers are experiencing delays due to a payment partner issue. "
                "Your money is safe; please retry after some time.")
    nid = db.insert("notices", incident_id=incident_id, text=text, status="draft", ts=db.iso())
    send("notice", "Customer notice drafted", f"Draft banner for incident #{incident_id} awaits approval", incident_id)
    return nid


def expire_notices(incident_id):
    db.ex("UPDATE notices SET status='expired' WHERE incident_id=? AND status IN ('draft','approved')", (incident_id,))
