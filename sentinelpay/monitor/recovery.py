"""Recovery with human approval, auto-resolve verification and fix-outcome learning.

No recovery action is ever executed except through approve(), which is only called by the
POST /api/incidents/{id}/approve endpoint (a human clicking Approve on the dashboard).
"""
from common import config, db, http
from monitor import alerts, events, reports
from monitor.rca import FIXES, cause_info


def _secs(a, b):
    if not a or not b:
        return None
    return int((db.parse(b) - db.parse(a)).total_seconds())


_noop_fixes = set()  # incidents whose approved action found no matching fault (not counted as learning)


def record_fix(incident, success):
    if not incident.get("recovery_action") or incident["id"] in _noop_fixes:
        return
    key = cause_info(incident["cause"])[1]
    db.insert("fix_history", cause=key, fix=incident["recovery_action"], success=1 if success else 0, ts=db.iso())


def resolve(incident_id, note, fix_success=None, count_mttr=True):
    inc = db.q1("SELECT * FROM incidents WHERE id=?", (incident_id,))
    if not inc or inc["status"] == "resolved":
        return
    now = db.iso()
    mttr = _secs(inc["detected_at"], now) if count_mttr else None
    db.update("incidents", incident_id, status="resolved", resolved_at=now, mttr_sec=mttr, resolution_note=note)
    if fix_success is not None:
        record_fix(inc, fix_success)
    alerts.expire_notices(incident_id)
    db.update("incidents", incident_id, report_md=reports.build_report(incident_id))
    msg = f"#{incident_id} {inc['cause']} – {note}"
    if mttr is not None:
        msg += f" (MTTR {reports.dur(mttr)})"
    alerts.send("resolved", "Incident resolved", msg, incident_id)


def approve(incident_id, approved_by="Ops Manager", action=None):
    inc = db.q1("SELECT * FROM incidents WHERE id=?", (incident_id,))
    if not inc:
        return False, "Incident not found"
    if inc["status"] != "open":
        return False, f"Incident is {inc['status']}; only open incidents can be approved"
    action = action or inc["suggested_fix"]
    if action not in FIXES:
        return False, f"Unknown recovery action {action}"
    if FIXES[action]["manual"]:
        return False, "No automatic fix for this cause. Review the rule with operations, or approve the optional action."
    try:
        r = http.client().post(f"{config.BANK_URL}/api/recovery/{action}", timeout=5)
        r.raise_for_status()
        result = r.json()
    except Exception as e:
        events.emit("crit", "RECOVERY", f"Recovery call {action} failed: {e}")
        return False, f"Bank recovery endpoint unreachable: {e}"
    if not result.get("cleared"):
        _noop_fixes.add(incident_id)
    now = db.iso()
    db.update("incidents", incident_id, status="recovering", approved_at=now, approved_by=approved_by or "Ops Manager",
              recovery_action=action, resolution_note=None)
    events.emit("ok", "AUTO_HEAL", f"{approved_by} approved '{FIXES[action]['label']}' for incident #{incident_id}: {result.get('message')}")
    alerts.send("approved", "Recovery approved",
                f"#{incident_id}: {FIXES[action]['label']} approved by {approved_by}", incident_id)
    from monitor.probe import PROBER
    PROBER.run_now()
    return True, result.get("message", "ok")


def dismiss(incident_id, by="Ops Manager"):
    inc = db.q1("SELECT * FROM incidents WHERE id=?", (incident_id,))
    if not inc:
        return False, "Incident not found"
    if inc["status"] == "resolved":
        return False, "Already resolved"
    resolve(incident_id, f"Dismissed as false positive by {by}", fix_success=None, count_mttr=False)
    return True, "dismissed"


_rt_fail_cycles = {}  # pattern-only incidents: failing probe cycles since approval


def verify_recovering(cycle):
    """Called after each probe cycle. cycle = {'any_fail': bool}"""
    for inc in db.q("SELECT * FROM incidents WHERE status='recovering'"):
        if inc["failed_step"] == "real transactions":
            if not cycle["any_fail"]:
                resolve(inc["id"], f"Recovered after approved action: {FIXES[inc['recovery_action']]['label']}", True)
            else:
                _rt_fail_cycles[inc["id"]] = _rt_fail_cycles.get(inc["id"], 0) + 1
                _check_failed_after_fix(inc, _rt_fail_cycles[inc["id"]])
                if _rt_fail_cycles[inc["id"]] >= 2:
                    _rt_fail_cycles.pop(inc["id"], None)
            continue
        runs = db.q("SELECT status FROM runs WHERE journey_id=? AND step=? AND attempt=1 AND ts>=? "
                    "AND status IN ('pass','slow','fail') ORDER BY id DESC",
                    (inc["journey_id"], inc["failed_step"], inc["approved_at"]))
        if not runs:
            continue
        if runs[0]["status"] in ("pass", "slow"):
            resolve(inc["id"], f"Recovered after approved action: {FIXES[inc['recovery_action']]['label']}", True)
        else:
            _check_failed_after_fix(inc, sum(1 for r in runs if r["status"] == "fail"))


def _check_failed_after_fix(inc, fails):
    if fails >= 2:
        record_fix(inc, False)
        db.update("incidents", inc["id"], status="open", resolution_note="Approved fix did not work; still failing")
        alerts.send("fix_failed", "Recovery did not work",
                    f"#{inc['id']}: {FIXES[inc['recovery_action']]['label']} failed – incident reopened", inc["id"])
