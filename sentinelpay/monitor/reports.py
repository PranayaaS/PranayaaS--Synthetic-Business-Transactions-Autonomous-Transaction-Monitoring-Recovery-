"""Plain-language incident report (Markdown) generated on resolution."""
from common import db
from monitor.rca import FIXES, LAYER_LABEL, cause_info, similar_incident


def inr(n):
    """Indian digit grouping: 1234567 -> 12,34,567."""
    n = int(n or 0)
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if n < 0 else "") + "₹" + s


def dur(sec):
    if sec is None:
        return "n/a"
    sec = int(sec)
    return f"{sec // 60}m {sec % 60:02d}s" if sec >= 60 else f"{sec}s"


def build_report(incident_id):
    inc = db.q1("SELECT * FROM incidents WHERE id=?", (incident_id,))
    if not inc:
        return ""
    j = db.q1("SELECT name FROM journeys WHERE id=?", (inc["journey_id"],)) or {"name": "-"}
    fix = FIXES.get(inc["recovery_action"] or "", {}).get("label", "None (no recovery action run)")
    sim = similar_incident(inc["cause"], incident_id)
    explanation = inc["ai_explanation"] or cause_info(inc["cause"])[3]
    lines = [
        f"# Incident #{inc['id']} – {inc['cause']}",
        "",
        f"**Severity:** {inc['severity']}  ",
        f"**Journey:** {j['name']}  ",
        f"**Failed step:** {inc['failed_step']}  ",
        f"**Failing layer:** {LAYER_LABEL.get(inc['layer'], inc['layer'])}  ",
        f"**Status:** {inc['status']}",
        "",
        "## What happened",
        explanation,
        "",
        f"Evidence: `{inc['error'] or 'n/a'}`" + (f" (HTTP {inc['http_status']})" if inc["http_status"] else ""),
        "",
        "## Timeline (UTC)",
        f"- Failure started: {inc['failure_started_at'] or '-'}",
        f"- Detected: {inc['detected_at'] or '-'}",
        f"- Alerted: {inc['alerted_at'] or '-'}",
        f"- Approved: {inc['approved_at'] or '-'}" + (f" by {inc['approved_by']}" if inc["approved_by"] else ""),
        f"- Resolved: {inc['resolved_at'] or '-'}",
        "",
        "## Business impact",
        f"- Failed transaction value: {inr(inc['impact_amount'])}",
        f"- Customers affected: {inc['impact_customers'] or 0}",
    ]
    if inc["pattern_summary"]:
        lines += ["", "## Pattern", inc["pattern_summary"]]
    lines += [
        "",
        "## Fix applied",
        fix,
    ]
    if inc["resolution_note"]:
        lines.append(f"\n_{inc['resolution_note']}_")
    if sim:
        lines += ["", f"Related: {sim['text']}"]
    lines += [
        "",
        "## Reliability metrics",
        f"- MTTD (time to detect): {dur(inc['mttd_sec'])}",
        f"- MTTR (time to resolve after detection): {dur(inc['mttr_sec'])}",
    ]
    if inc["screenshot"]:
        lines += ["", f"Evidence screenshot: `screenshots/{inc['screenshot']}`"]
    lines += ["", "---", "_Generated automatically by SentinelPay – Transaction Health Engine._"]
    return "\n".join(lines)
