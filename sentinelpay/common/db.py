"""SQLite helpers, schema and first-run seed data.

A new connection is opened per operation so the probe thread, the engine thread and
the FastAPI handlers never share a connection.
"""
import random
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from common import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS journeys (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE, description TEXT,
  amount INTEGER DEFAULT 500, receiver_bank TEXT DEFAULT 'DDCCB',
  auto_created INTEGER DEFAULT 0, created_from_pattern TEXT, created_at TEXT,
  active INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, journey_id INTEGER, run_group TEXT, step TEXT,
  status TEXT, latency_ms INTEGER, error TEXT, http_status INTEGER,
  screenshot TEXT, ts TEXT, attempt INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY, journey_id INTEGER, severity TEXT,
  status TEXT, failed_step TEXT, layer TEXT, cause TEXT, ai_explanation TEXT,
  similar_incident_id INTEGER, pattern_summary TEXT,
  impact_amount INTEGER DEFAULT 0, impact_customers INTEGER DEFAULT 0,
  suggested_fix TEXT, screenshot TEXT,
  failure_started_at TEXT, detected_at TEXT, alerted_at TEXT,
  approved_at TEXT, approved_by TEXT, resolved_at TEXT,
  mttd_sec INTEGER, mttr_sec INTEGER, report_md TEXT,
  last_seen TEXT, recovery_action TEXT, pattern_signature TEXT,
  error TEXT, http_status INTEGER, run_group TEXT, resolution_note TEXT);

CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY, txn_ref TEXT, customer_id TEXT, amount INTEGER,
  receiver_bank TEXT, status TEXT,
  failure_layer TEXT, error_code TEXT, ts TEXT,
  reversal_deadline TEXT, reversed_at TEXT, synthetic INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS patterns (
  id INTEGER PRIMARY KEY, signature TEXT UNIQUE, receiver_bank TEXT,
  amount_min INTEGER, amount_max INTEGER, failure_count INTEGER,
  first_seen TEXT, last_seen TEXT, test_journey_id INTEGER, summary TEXT, layer TEXT);

CREATE TABLE IF NOT EXISTS fix_history (
  id INTEGER PRIMARY KEY, cause TEXT, fix TEXT, success INTEGER, ts TEXT);

CREATE TABLE IF NOT EXISTS notices (
  id INTEGER PRIMARY KEY, incident_id INTEGER, text TEXT,
  status TEXT, ts TEXT);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY, incident_id INTEGER, channel TEXT, message TEXT, ts TEXT,
  kind TEXT, title TEXT);

CREATE TABLE IF NOT EXISTS bank_logs (
  id INTEGER PRIMARY KEY, ts TEXT, endpoint TEXT, method TEXT,
  http_status INTEGER, duration_ms INTEGER, layer_hint TEXT, message TEXT);

CREATE INDEX IF NOT EXISTS ix_runs_ts ON runs(ts);
CREATE INDEX IF NOT EXISTS ix_runs_js ON runs(journey_id, step, ts);
CREATE INDEX IF NOT EXISTS ix_txn_ts ON transactions(ts);
CREATE INDEX IF NOT EXISTS ix_txn_status ON transactions(status);
CREATE INDEX IF NOT EXISTS ix_logs_ts ON bank_logs(ts);
"""

TS_FMT = "%Y-%m-%dT%H:%M:%SZ"

# Core journeys and the probe steps each one covers.
CORE_JOURNEYS = [
    ("Login", "Customer signs in to internet banking", ["login"]),
    ("Fund Transfer", "Open transfer form and submit payee + amount", ["open_transfer", "submit_transfer"]),
    ("UPI Payment", "Payment request through the payment gateway", ["gateway_pay"]),
    ("Payment Confirmation", "Receipt shows the correct amount and status", ["verify_receipt"]),
]
ALL_STEPS = ["login", "open_transfer", "submit_transfer", "gateway_pay", "verify_receipt"]
CORE_STEP_MAP = {name: steps for name, _, steps in CORE_JOURNEYS}


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt=None):
    return (dt or utcnow()).strftime(TS_FMT)


def parse(ts):
    if not ts:
        return None
    return datetime.strptime(ts, TS_FMT).replace(tzinfo=timezone.utc)


def ago(**kw):
    return iso(utcnow() - timedelta(**kw))


def connect():
    conn = sqlite3.connect(str(config.DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def q(sql, args=()):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def q1(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def ex(sql, args=()):
    conn = connect()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def exmany(sql, rows):
    conn = connect()
    try:
        conn.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()


def update(table, row_id, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    ex(f"UPDATE {table} SET {cols} WHERE id=?", (*fields.values(), row_id))


def insert(table, **fields):
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    return ex(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(fields.values()))


def init_schema():
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def journey_steps(journey):
    """Steps a journey is judged on. Auto-created journeys cover the full flow."""
    return CORE_STEP_MAP.get(journey["name"], ALL_STEPS) if not journey.get("auto_created") else ALL_STEPS


# --------------------------------------------------------------------------- seed

def _txn_ref():
    return "TXN" + uuid.uuid4().hex[:10].upper()


def _amount(rng):
    if rng.random() < 0.10:
        return rng.randrange(50_000, 200_000, 500)
    if rng.random() < 0.15:
        return rng.randrange(10_000, 50_000, 100)
    return rng.randrange(100, 10_000, 10)


BANKS = ["DDCCB", "Bank X", "Bank Y", "SBI"]


def seed_if_empty():
    if q1("SELECT COUNT(*) AS n FROM journeys")["n"] > 0:
        return False
    seed()
    return True


def seed():
    rng = random.Random(26)
    now = utcnow()

    # Journeys
    for name, desc, _ in CORE_JOURNEYS:
        insert("journeys", name=name, description=desc, amount=500, receiver_bank="DDCCB",
               auto_created=0, created_at=iso(now - timedelta(days=30)), active=1)
    jid = {r["name"]: r["id"] for r in q("SELECT id, name FROM journeys")}

    # ~60 minutes of background customer transactions (mostly successful, ~1% network noise)
    txns = []
    t = now - timedelta(minutes=60)
    while t < now - timedelta(seconds=5):
        for _ in range(rng.randint(1, 3)):
            amt = _amount(rng)
            status, layer, code = "success", None, None
            if rng.random() < 0.01:
                status, layer, code = "failed", "customer_network", "NET_DROP"
            txns.append((_txn_ref(), f"CUST{rng.randint(1000, 9999)}", amt, rng.choice(BANKS),
                         status, layer, code, iso(t), None, None, 0))
        t += timedelta(seconds=rng.choice([4, 5, 6]))
    exmany("INSERT INTO transactions (txn_ref, customer_id, amount, receiver_bank, status, failure_layer,"
           " error_code, ts, reversal_deadline, reversed_at, synthetic) VALUES (?,?,?,?,?,?,?,?,?,?,?)", txns)

    # Debited-but-not-credited transactions so the RBI watchdog is populated immediately
    dnc = [(74_500, "Bank X", 2.5), (1_20_000, "Bank Y", 6), (12_800, "SBI", 9)]
    for amt, bank, mins in dnc:
        ts = now - timedelta(minutes=max(3, config.DEMO_DEADLINE_MINUTES - mins)) if config.DEMO_MODE else now - timedelta(hours=20)
        deadline = now + timedelta(minutes=mins) if config.DEMO_MODE else now + timedelta(hours=mins)
        insert("transactions", txn_ref=_txn_ref(), customer_id=f"CUST{rng.randint(1000, 9999)}", amount=amt,
               receiver_bank=bank, status="debited_not_credited", failure_layer="gateway", error_code="GW_TIMEOUT",
               ts=iso(ts), reversal_deadline=iso(deadline), synthetic=0)

    # 30 minutes of green probe history so the latency chart is not empty
    base_lat = {"login": 420, "open_transfer": 160, "submit_transfer": 120, "gateway_pay": 260, "verify_receipt": 140}
    owner = {s: jid[n] for n, _, steps in CORE_JOURNEYS for s in steps}
    runs = []
    t = now - timedelta(minutes=30)
    while t < now - timedelta(seconds=20):
        g = uuid.uuid4().hex
        for i, step in enumerate(ALL_STEPS):
            lat = int(base_lat[step] * rng.uniform(0.8, 1.35))
            runs.append((owner[step], g, step, "pass", lat, None, 200, None, iso(t + timedelta(seconds=i)), 1))
        t += timedelta(seconds=config.PROBE_INTERVAL_SEC)
    exmany("INSERT INTO runs (journey_id, run_group, step, status, latency_ms, error, http_status, screenshot, ts, attempt)"
           " VALUES (?,?,?,?,?,?,?,?,?,?)", runs)

    # Fix history (learned outcomes)
    hist = ([("gateway", "switch_backup_gateway", 1)] * 4 + [("gateway", "switch_backup_gateway", 0)]
            + [("server_error", "restart_payment_service", 1)] * 2 + [("server_error", "restart_payment_service", 0)]
            + [("receiver_bank", "pause_receiver_bank", 1)] * 3
            + [("data_integrity", "rollback_receipt_service", 1)] * 2)
    for i, (cause, fix, ok) in enumerate(hist):
        insert("fix_history", cause=cause, fix=fix, success=ok, ts=iso(now - timedelta(days=40 - i * 3)))

    # Four resolved past incidents
    past = [
        dict(days=12, journey="UPI Payment", severity="critical", step="gateway_pay", layer="gateway",
             cause="Payment gateway unavailable", fix="switch_backup_gateway", mttd=38, mttr=412, http=502,
             error="HTTP 502: Payment gateway unavailable", amount=612_400, customers=143,
             pattern="143 customers failed in 2 min across all banks and amounts"),
        dict(days=7, journey="UPI Payment", severity="critical", step="gateway_pay", layer="gateway",
             cause="Payment gateway timeout", fix="switch_backup_gateway", mttd=44, mttr=355, http=None,
             error="Timeout 6000ms waiting for /api/pay", amount=388_900, customers=91,
             pattern="91 customers affected; 37 debited but not credited"),
        dict(days=4, journey="Payment Confirmation", severity="major", step="verify_receipt", layer="server",
             cause="Data integrity error in payment confirmation", fix="rollback_receipt_service", mttd=31, mttr=268,
             http=200, error="Receipt amount 501 != submitted 500", amount=0, customers=0, pattern=None),
        dict(days=2, journey="Fund Transfer", severity="major", step="real transactions", layer="receiver_bank",
             cause="Receiver bank not responding", fix="pause_receiver_bank", mttd=52, mttr=486, http=503,
             error="HTTP 503: RB_UNAVAILABLE", amount=241_300, customers=57,
             pattern="57 customers failed in 2 min, all to Bank X"),
    ]
    from monitor import reports  # local import to avoid a cycle at module load
    from monitor.rca import FIXES
    for p in past:
        start = now - timedelta(days=p["days"], hours=rng.randint(1, 8))
        detected = start + timedelta(seconds=p["mttd"])
        alerted = detected + timedelta(seconds=2)
        approved = detected + timedelta(seconds=int(p["mttr"] * 0.6))
        resolved = detected + timedelta(seconds=p["mttr"])
        iid = insert("incidents", journey_id=jid[p["journey"]], severity=p["severity"], status="resolved",
                     failed_step=p["step"], layer=p["layer"], cause=p["cause"], pattern_summary=p["pattern"],
                     impact_amount=p["amount"], impact_customers=p["customers"], suggested_fix=p["fix"],
                     failure_started_at=iso(start), detected_at=iso(detected), alerted_at=iso(alerted),
                     approved_at=iso(approved), approved_by="Ops Manager", resolved_at=iso(resolved),
                     mttd_sec=p["mttd"], mttr_sec=p["mttr"], last_seen=iso(approved), recovery_action=p["fix"],
                     error=p["error"], http_status=p["http"],
                     resolution_note=f"Recovered after approved action: {FIXES[p['fix']]['label']}")
        update("incidents", iid, report_md=reports.build_report(iid))
        insert("alerts", incident_id=iid, channel="in-app", kind="resolved", title="Incident resolved",
               message=f"Incident #{iid} resolved: {p['cause']}", ts=iso(resolved))
