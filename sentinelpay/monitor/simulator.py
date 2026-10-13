"""Real-customer transaction simulator. Outcomes mirror the bank's current chaos mode."""
import random
import uuid
from datetime import timedelta

from common import config, db, http
from monitor import events

BANKS = ["DDCCB", "Bank X", "Bank Y", "SBI"]
rng = random.Random()
CHAOS = {"state": None, "reachable": True}


def fetch_chaos():
    try:
        r = http.client().get(f"{config.BANK_URL}/api/chaos", timeout=1.5)
        CHAOS["state"] = r.json()
        if not CHAOS["reachable"]:
            events.emit("ok", "SIMULATOR", "Bank reachable again – customer traffic resumed")
        CHAOS["reachable"] = True
    except Exception:
        if CHAOS["reachable"]:
            events.emit("warn", "SIMULATOR", "Bank unreachable – customer traffic simulator paused")
        CHAOS["reachable"] = False
        CHAOS["state"] = None
    return CHAOS["state"]


def amount():
    r = rng.random()
    if r < 0.10:
        return rng.randrange(50_000, 200_000, 500)
    if r < 0.25:
        return rng.randrange(10_000, 50_000, 100)
    return rng.randrange(100, 10_000, 10)


def deadline_from(ts):
    if config.DEMO_MODE:
        return ts + timedelta(minutes=config.DEMO_DEADLINE_MINUTES)
    return ts + timedelta(days=1)


def tick():
    state = fetch_chaos()
    if state is None:
        return 0
    mode, paused = state["mode"], set(state.get("paused_banks") or [])
    now = db.utcnow()
    rows = []
    for _ in range(rng.randint(1, 3)):
        amt, bank = amount(), rng.choice(BANKS)
        status, layer, code, deadline = "success", None, None, None
        r = rng.random()
        if bank == "Bank X" and "Bank X" in paused:
            pass  # queued by operations: customer sees a friendly message, not a failure
        elif mode == "gateway_down" and r < 0.9:
            status, layer, code = "failed", "gateway", "GW_UNAVAILABLE"
        elif mode == "intermittent" and r < 0.4:
            status, layer, code = "failed", "gateway", "GW_UNAVAILABLE"
        elif mode == "gateway_timeout" and r < 0.5:
            status, layer, code = "debited_not_credited", "gateway", "GW_TIMEOUT"
            deadline = db.iso(deadline_from(now))
        elif mode == "receiver_bank_down" and bank == "Bank X":
            status, layer, code = "failed", "receiver_bank", "RB_UNAVAILABLE"
        elif mode == "large_amount_fail" and amt > 50_000:
            status, layer, code = "failed", "server", "LIMIT_OR_RISK_CHECK"
        elif rng.random() < 0.01:
            status, layer, code = "failed", "customer_network", "NET_DROP"
        rows.append(("TXN" + uuid.uuid4().hex[:10].upper(), f"CUST{rng.randint(1000, 9999)}", amt, bank, status,
                     layer, code, db.iso(now), deadline, None, 0))
    db.exmany("INSERT INTO transactions (txn_ref, customer_id, amount, receiver_bank, status, failure_layer, error_code,"
              " ts, reversal_deadline, reversed_at, synthetic) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)
