"""End-to-end acceptance checks (Section 14) against a running SentinelPay (python run.py).

Usage: python acceptance_test.py            (takes ~10-12 minutes; drives chaos modes via the API)
Run on a freshly reset database (python reset_db.py) for check 1 to be meaningful.
"""
import json
import sys
import time
import urllib.error
import urllib.request

M = "http://127.0.0.1:8000"
results = []


def call(method, path, body=None, raw=False):
    req = urllib.request.Request(M + path, method=method, headers={"Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read().decode("utf-8")
        return data if raw else json.loads(data)


def get(p, raw=False):
    return call("GET", p, raw=raw)


def post(p, body=None):
    try:
        return call("POST", p, body or {})
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()}


def check(n, name, ok, detail=""):
    results.append((n, name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {n:>2}. {name}" + (f" – {detail}" if detail else ""), flush=True)


def wait_for(fn, timeout, every=3, kick=True):
    t0 = time.time()
    last_kick = 0
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        if kick and time.time() - last_kick > 10:
            post("/api/probe/run")
            last_kick = time.time()
        time.sleep(every)
    return None


def open_incidents():
    return get("/api/incidents?status=open,recovering")


def approve_all():
    for i in open_incidents():
        if i["status"] != "open":
            continue
        fix = i.get("fix") or {}
        action = fix.get("optional", {}).get("action") if fix.get("manual") else None
        post(f"/api/incidents/{i['id']}/approve", {"approved_by": "Acceptance test", "action": action})


def settle():
    """Reset chaos, close any leftovers and wait until all journeys are green."""
    approve_all()
    post("/api/chaos/none")
    for i in open_incidents():
        if i["status"] == "open":
            post(f"/api/incidents/{i['id']}/dismiss", {"by": "Acceptance test"})
    wait_for(lambda: not open_incidents() and all(j["health"] == "green" for j in get("/api/status")["journeys"]), 90)


def main():
    # 1. Seeded data
    s = get("/api/status")
    inc = get("/api/incidents?status=resolved")
    wd = get("/api/watchdog")
    lat = get("/api/latency?minutes=30")
    lay = get("/api/layers?minutes=60")
    fix = [i for i in inc if i["cause"] == "Payment gateway unavailable"]
    check(1, "Services up with seeded data",
          len(inc) >= 4 and wd["summary"]["count"] >= 3 and len(lat["labels"]) > 10 and lay["total_txns"] > 100
          and get("/", raw=True).startswith("<!DOCTYPE html>"),
          f"{len(inc)} past incidents, {wd['summary']['count']} watchdog rows, {len(lat['labels'])} latency points, "
          f"{lay['total_txns']} txns")

    # 2. All green with chaos none
    post("/api/chaos/none")
    ok = wait_for(lambda: all(j["health"] == "green" for j in get("/api/status")["journeys"]), 45)
    check(2, "Chaos none → all journeys green", ok, f"{get('/api/status')['kpis']['journeys_healthy']}/4 healthy")

    # 3. gateway_down
    last_alert = max([a["id"] for a in get("/api/alerts?limit=1")] or [0])
    post("/api/chaos/gateway_down")
    t0 = time.time()
    found = wait_for(lambda: next((i for i in open_incidents() if i["layer"] == "gateway" and i["screenshot"]), None), 75)
    took = round(time.time() - t0)
    d = get(f"/api/incidents/{found['id']}") if found else {}
    alerts = get(f"/api/alerts?since={last_alert}")
    notice = [n for n in get("/api/notices") if found and n["incident_id"] == found["id"] and n["status"] == "draft"]
    ok3 = bool(found) and d["cause"] == "Payment gateway unavailable" and d["layer_label"] == "Payment gateway" \
        and d["similar"] and d["fix"]["label"] == "Switch to backup gateway" and d["fix"]["worked"] == 4 \
        and d["fix"]["total"] == 5 and d["impact_amount"] > 0 and alerts and notice
    check(3, "gateway_down → full incident", ok3,
          f"in {took}s: {d.get('cause')} / {d.get('layer_label')} / {(d.get('fix') or {}).get('history_text')} / "
          f"₹{d.get('impact_amount')} / {len(alerts)} alerts / notice={bool(notice)}" if found else "no incident")

    # 5. Nothing recovers without approval
    time.sleep(35)
    still = get(f"/api/incidents/{found['id']}") if found else {}
    chaos = get("/api/chaos")
    check(5, "No recovery without Approve", still.get("status") == "open" and not still.get("approved_at")
          and chaos["mode"] == "gateway_down", f"after 35s: status={still.get('status')}, chaos={chaos['mode']}")

    # 4. Approve → resolved
    r = post(f"/api/incidents/{found['id']}/approve", {"approved_by": "Acceptance test"})
    res = wait_for(lambda: (lambda x: x if x["status"] == "resolved" else None)(get(f"/api/incidents/{found['id']}")), 45)
    rep = get(f"/api/incidents/{found['id']}/report", raw=True) if res else ""
    check(4, "Approve → resolved with MTTD/MTTR + report",
          res and res["mttd_sec"] is not None and res["mttr_sec"] is not None and "MTTR" in rep and get("/api/chaos")["mode"] == "none",
          f"approve={r.get('message')}, MTTD={res and res['mttd_sec']}s, MTTR={res and res['mttr_sec']}s")
    settle()

    # 6. wrong_amount
    post("/api/chaos/wrong_amount")
    f6 = wait_for(lambda: next((i for i in open_incidents() if i["failed_step"] == "verify_receipt"), None), 60)
    check(6, "wrong_amount → verify_receipt data-integrity incident",
          f6 and f6["cause"] == "Data integrity error in payment confirmation", f6 and f6["cause"])
    settle()

    # 7. receiver_bank_down
    post("/api/chaos/receiver_bank_down")
    f7 = wait_for(lambda: next((i for i in open_incidents() if "all to Bank X" in (i["pattern_summary"] or "")), None), 120)
    t7 = wait_for(lambda: next((t for t in get("/api/tests")["tests"] if t["name"] == "Transfer to Bank X" and t["last_run"]), None), 60)
    check(7, "receiver_bank_down → Bank X pattern + auto test runs",
          f7 and f7["impact_amount"] > 0 and t7 and t7["auto_created"],
          f"{f7 and f7['pattern_summary']} · ₹{f7 and f7['impact_amount']} · test last run {t7 and t7['last_run']}")
    settle()

    # 8. large_amount_fail
    post("/api/chaos/large_amount_fail")
    f8 = wait_for(lambda: next((i for i in open_incidents() if "above ₹50,000" in (i["pattern_summary"] or "")), None), 200)
    t8 = wait_for(lambda: next((t for t in get("/api/tests")["tests"] if t["name"] == "Transfer above ₹50,000"), None), 30)
    check(8, "large_amount_fail → >₹50k pattern + auto test", f8 and t8 and t8["auto_created"],
          f"{f8 and f8['pattern_summary']} · test={t8 and t8['name']}")
    settle()

    # 9. gateway_timeout → watchdog
    before = get("/api/watchdog")["summary"]["count"]
    post("/api/chaos/gateway_timeout")
    grew = wait_for(lambda: (lambda c: c if c > before + 3 else None)(get("/api/watchdog")["summary"]["count"]), 60, kick=False)
    rows = get("/api/watchdog")["rows"]
    one = post(f"/api/watchdog/{rows[0]['id']}/reverse") if rows else {}
    allr = post("/api/watchdog/reverse-all")
    check(9, "gateway_timeout → DNC in watchdog, Reverse works",
          grew and one.get("ok") and allr.get("reversed", 0) > 0 and all("remaining_sec" in r for r in rows),
          f"DNC {before}→{grew}, reversed 1 + {allr.get('reversed')}")
    settle()

    # 10. slow_gateway → warning before failure
    post("/api/chaos/slow_gateway")
    w = wait_for(lambda: next((i for i in get("/api/incidents?status=open,recovering,resolved&limit=5")
                               if i["cause"] == "Payment gateway latency rising"), None), 120, every=4)
    alerts = get("/api/alerts?limit=50")
    warn_alert = any("Warning incident" in (a["title"] or "") and "latency" in a["message"].lower() for a in alerts)
    check(10, "slow_gateway → amber early warning", w and warn_alert, f"incident #{w and w['id']} severity now {w and w['severity']}")
    settle()

    # 11. intermittent
    post("/api/chaos/intermittent")
    f11 = wait_for(lambda: next((i for i in open_incidents() if i["cause"] == "Intermittent payment gateway failures"), None), 150)
    check(11, "intermittent → intermittent incident", f11, f11 and f"#{f11['id']} on {f11['failed_step']}")
    settle()

    passed = sum(1 for r in results if r[2])
    print(f"\n{passed}/{len(results)} automated checks passed. (12: stop the bank process manually; 13: no .env/Slack/Gemini needed.)")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
