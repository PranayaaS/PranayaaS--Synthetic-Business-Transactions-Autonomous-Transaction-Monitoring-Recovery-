"""Failure pattern engine, business impact and self-expanding synthetic tests."""
from collections import Counter

from common import db
from monitor import alerts, events, rca

BUCKETS = {"<10k": (0, 9_999), "10k–50k": (10_000, 50_000), ">50k": (50_001, 10**9)}
BUCKET_TEXT = {">50k": "all transfers above ₹50,000", "10k–50k": "all transfers between ₹10,000 and ₹50,000",
               "<10k": "all transfers below ₹10,000"}


def bucket(amount):
    for name, (lo, hi) in BUCKETS.items():
        if lo <= amount <= hi:
            return name
    return ">50k"


def _specific(fails, txns, key):
    """Return the one bank / amount bucket the failures concentrate on, or None if they are spread out."""
    counts = Counter(key(t) for t in fails)
    top, cnt = counts.most_common(1)[0]
    if cnt / len(fails) < 0.9:
        return None
    total_top = sum(1 for t in txns if key(t) == top)
    others_total = len(txns) - total_top
    if others_total < 8:
        return None  # not enough comparison traffic to claim the failures are specific
    rate_top = cnt / total_top if total_top else 0
    rate_other = (len(fails) - cnt) / others_total
    # Specific only if this bank/bucket fails heavily while the rest of traffic is essentially healthy.
    return top if rate_top >= 0.6 and rate_other < 0.1 else None


def describe(n_customers, bank, bkt, dnc):
    if bank and bkt:
        scope = f"{BUCKET_TEXT[bkt]} to {bank}"
    elif bank:
        scope = f"all to {bank}"
    elif bkt:
        scope = BUCKET_TEXT[bkt]
    else:
        scope = "across all banks and amounts"
    s = f"{n_customers} customers failed in 2 min, {scope}"
    if dnc:
        s += f" · {dnc} debited but not credited"
    return s


def parse_signature(sig):
    if not sig or sig.count("|") != 2:
        return None, None
    _, bank, bkt = sig.split("|")
    return (None if bank == "ANY" else bank), (None if bkt == "ANY" else bkt)


def refresh_impact(incident_id):
    inc = db.q1("SELECT * FROM incidents WHERE id=?", (incident_id,))
    if not inc or inc["status"] == "resolved":
        return
    codes = rca.CAUSE_CODES.get(inc["cause"])
    rows = db.q("SELECT customer_id, amount, receiver_bank, error_code FROM transactions WHERE synthetic=0"
                " AND status IN ('failed','debited_not_credited') AND failure_layer=? AND ts >= ?",
                (inc["layer"], inc["failure_started_at"] or inc["detected_at"]))
    bank, bkt = parse_signature(inc["pattern_signature"])
    rows = [r for r in rows if (codes is None or r["error_code"] in codes)
            and (not bank or r["receiver_bank"] == bank) and (not bkt or bucket(r["amount"]) == bkt)]
    db.update("incidents", incident_id, impact_amount=sum(r["amount"] for r in rows),
              impact_customers=len({r["customer_id"] for r in rows}))


def _create_test(sig, bank, bkt, summary):
    if bkt == ">50k":
        name, amount = "Transfer above ₹50,000", 75_000
    elif bkt == "10k–50k":
        name, amount = "Transfer between ₹10,000 and ₹50,000", 30_000
    elif bkt == "<10k":
        name, amount = "Transfer below ₹10,000", 5_000
    else:
        name, amount = None, 500
    if bank:
        name = f"{name} to {bank}" if name else f"Transfer to {bank}"
    receiver = bank or "DDCCB"
    existing = db.q1("SELECT * FROM journeys WHERE name=?", (name,))
    if existing:
        db.update("journeys", existing["id"], active=1)
        jid = existing["id"]
    else:
        jid = db.insert("journeys", name=name, description=f"Auto-created from pattern: {summary}", amount=amount,
                        receiver_bank=receiver, auto_created=1, created_from_pattern=sig, created_at=db.iso(),
                        active=1)
    db.ex("UPDATE patterns SET test_journey_id=? WHERE signature=?", (jid, sig))
    alerts.send("test_created", "New test auto-created from pattern",
                f"'{name}' (₹{amount:,} to {receiver}) added to the probe schedule – {summary}")
    from monitor.probe import PROBER
    PROBER.run_now()
    return jid


def tick():
    since = db.ago(minutes=2)
    txns = db.q("SELECT customer_id, amount, receiver_bank, status, failure_layer, error_code, ts FROM transactions"
                " WHERE synthetic=0 AND ts >= ?", (since,))
    all_fails = [t for t in txns if t["status"] in ("failed", "debited_not_credited")
                 and t["failure_layer"] and t["failure_layer"] != "customer_network"]
    by_layer = {}
    for t in all_fails:
        by_layer.setdefault(t["failure_layer"], []).append(t)

    for layer, lf in by_layer.items():
        code = Counter(t["error_code"] for t in lf).most_common(1)[0][0]
        cause = rca.CODE_CAUSE.get(code, "Bank application server error")
        last_res = (db.q1("SELECT MAX(resolved_at) AS t FROM incidents WHERE layer=? AND status='resolved'", (layer,))
                    or {}).get("t") or ""
        lf = [t for t in lf if t["ts"] > last_res]  # ignore failures that belong to an already-resolved incident
        if len(lf) < 5:
            continue
        # Compare against traffic since the failures began, not the healthy traffic before them.
        first = min(t["ts"] for t in lf)
        window = [t for t in txns if t["ts"] >= first]
        if code == "GW_UNAVAILABLE" and len(lf) / max(1, len(window)) < 0.7:
            cause = "Intermittent payment gateway failures"  # partial failure rate across all traffic
        bank = _specific(lf, window, lambda t: t["receiver_bank"])
        bkt = _specific(lf, window, lambda t: bucket(t["amount"]))
        sig = f"{layer}|{bank or 'ANY'}|{bkt or 'ANY'}"
        customers = len({t["customer_id"] for t in lf})
        dnc = sum(1 for t in lf if t["status"] == "debited_not_credited")
        summary = describe(customers, bank, bkt, dnc)
        lo, hi = BUCKETS[bkt] if bkt else (0, None)
        now = db.iso()

        pat = db.q1("SELECT * FROM patterns WHERE signature=?", (sig,))
        if pat:
            db.update("patterns", pat["id"], failure_count=len(lf), last_seen=now, summary=summary)
        else:
            db.insert("patterns", signature=sig, receiver_bank=bank or "ANY", amount_min=lo, amount_max=hi,
                      failure_count=len(lf), first_seen=now, last_seen=now, summary=summary, layer=layer)
            alerts.send("pattern", "Failure pattern detected", f"{summary} (layer: {rca.LAYER_LABEL.get(layer, layer)})")
            events.emit("crit", "PATTERN", f"New pattern {sig}: {summary}")

        # Attach to the related open incident, or open one from the pattern.
        incs = db.q("SELECT * FROM incidents WHERE status IN ('open','recovering') AND layer=? ORDER BY id DESC", (layer,))
        incs = [i for i in incs if i["cause"] == cause] or [i for i in incs if i["cause"] in rca.CAUSES
                                                             and rca.CAUSE_CODES.get(i["cause"]) is None
                                                             and rca.CAUSE_CODES.get(cause) is None]
        if not incs:
            fund = db.q1("SELECT id FROM journeys WHERE name='Fund Transfer'")
            from monitor import detector
            iid = detector.raise_incident(fund["id"], "real transactions", cause, "critical",
                                          error=f"{len(lf)} real customer transactions failed with {code}",
                                          started=min(t["ts"] for t in lf))
            incs = [db.q1("SELECT * FROM incidents WHERE id=?", (iid,))]
        for inc in incs:
            db.update("incidents", inc["id"], pattern_summary=summary, pattern_signature=sig)
            refresh_impact(inc["id"])

        if not pat and (bank or bkt):
            _create_test(sig, bank, bkt, summary)
        elif pat and not pat["test_journey_id"] and (bank or bkt):
            _create_test(sig, bank, bkt, summary)

    # Keep impact current for every open incident, and close pattern-only incidents whose failures stopped.
    for inc in db.q("SELECT * FROM incidents WHERE status IN ('open','recovering')"):
        refresh_impact(inc["id"])
        if inc["failed_step"] == "real transactions" and inc["status"] == "open":
            recent = db.q1("SELECT COUNT(*) AS n FROM transactions WHERE synthetic=0 AND failure_layer=? AND ts >= ?"
                           " AND status IN ('failed','debited_not_credited')", (inc["layer"], db.ago(seconds=60)))
            if recent["n"] == 0 and inc["detected_at"] < db.ago(seconds=60):
                from monitor import recovery
                recovery.resolve(inc["id"], "Failures in real transactions stopped (auto-closed)", None, count_mttr=False)
