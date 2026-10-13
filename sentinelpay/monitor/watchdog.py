"""RBI deadline watchdog for debited-but-not-credited transactions.

Deadlines and compensation are configurable and based on RBI TAT guidelines for failed
transactions; verify against current RBI circulars. Not legal advice.
"""
import math

from common import config, db
from monitor import alerts, events

_warned = set()


def _unit_sec():
    # Demo mode compresses time: one demo-minute late counts as one day late.
    return 60 if config.DEMO_MODE else 86_400


def _warn_window():
    return 180 if config.DEMO_MODE else 3 * 3600


def rows():
    now = db.utcnow()
    out = []
    for t in db.q("SELECT * FROM transactions WHERE status='debited_not_credited' ORDER BY reversal_deadline"):
        deadline = db.parse(t["reversal_deadline"]) if t["reversal_deadline"] else now
        remaining = int((deadline - now).total_seconds())
        if remaining < 0:
            status = "breached"
            late_units = math.ceil(-remaining / _unit_sec())
            penalty = late_units * config.PENALTY_PER_DAY
        else:
            status = "warning" if remaining < _warn_window() else "ok"
            late_units, penalty = 0, 0
        out.append({**t, "remaining_sec": remaining, "watch_status": status, "days_late": late_units,
                    "penalty": penalty})
    return out


def summary():
    rs = rows()
    value = sum(r["amount"] for r in rs)
    nxt = min((r["remaining_sec"] for r in rs if r["remaining_sec"] >= 0), default=None)
    return {
        "rows": rs,
        "summary": {
            "count": len(rs), "value": value, "next_deadline_sec": nxt,
            "warning": sum(1 for r in rs if r["watch_status"] == "warning"),
            "breached": sum(1 for r in rs if r["watch_status"] == "breached"),
            "penalty": sum(r["penalty"] for r in rs),
            "reversed_today": db.q1("SELECT COUNT(*) AS n FROM transactions WHERE status='reversed' AND reversed_at >= ?",
                                    (db.ago(hours=24),))["n"],
        },
        "config": {"demo_mode": config.DEMO_MODE, "deadline_minutes": config.DEMO_DEADLINE_MINUTES,
                   "penalty_per_day": config.PENALTY_PER_DAY, "warn_window_sec": _warn_window(),
                   "rule": "T+1 day reversal for UPI-style transfers (configurable)"},
    }


def tick():
    new = [r for r in rows() if r["watch_status"] in ("warning", "breached") and r["id"] not in _warned]
    if new:
        _warned.update(r["id"] for r in new)
        total = sum(r["amount"] for r in new)
        alerts.send("watchdog", "RBI deadline warning",
                    f"{len(new)} debited-not-credited transaction(s) worth ₹{total:,} near or past reversal deadline")


def reverse(txn_id):
    t = db.q1("SELECT * FROM transactions WHERE id=? AND status='debited_not_credited'", (txn_id,))
    if not t:
        return False
    db.update("transactions", txn_id, status="reversed", reversed_at=db.iso())
    events.emit("audit", "RBI_AUDIT", f"Reversed {t['txn_ref']} ₹{t['amount']:,} for {t['customer_id']}")
    return True


def reverse_all():
    ids = [r["id"] for r in rows()]
    for i in ids:
        db.update("transactions", i, status="reversed", reversed_at=db.iso())
    if ids:
        events.emit("audit", "RBI_AUDIT", f"Bulk reversal of {len(ids)} debited-not-credited transactions")
    return len(ids)
