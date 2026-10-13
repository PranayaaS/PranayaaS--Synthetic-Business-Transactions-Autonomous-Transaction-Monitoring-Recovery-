# SentinelPay – Transaction Health Engine

**Synesis 26 · Business Automations · Problem Statement 2 — Autonomous Transaction Monitoring & Recovery**

> GPay tells one customer why their payment failed. SentinelPay tells the bank why many payments are failing,
> before complaints start, and helps fix it safely.

SentinelPay watches a cooperative bank's digital payment journeys with synthetic browser probes and a stream of
(simulated) real customer transactions. It detects failures, names the failing layer, estimates the rupee impact,
alerts the team, drafts a customer notice, tracks RBI reversal deadlines, and runs a recovery action **only after a
human approves it**.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python run.py
```

```
SentinelPay running
  Dashboard : http://localhost:8000
  Mock bank : http://localhost:8001   (login: demo / demo123)
```

Optional, once while online, so the dashboard also works with no internet (caches Tailwind, Chart.js and fonts,
~5 MB, into `monitor/static/vendor/`):

```bash
python vendor_assets.py
```

Clean slate before a demo (stop `run.py` first): `python reset_db.py`.
Automated end-to-end check of Section 14 against a running instance (~10 min): `python acceptance_test.py`.

> **Note:** `run.py` listens on both `127.0.0.1` and `::1`, so `http://localhost:8000` reaches SentinelPay even if
> another program (e.g. `python -m http.server 8000`) holds the IPv6 wildcard address on port 8000.
> If the terminal shows *"Executable doesn't exist … playwright install"*, run
> `python -m playwright install chromium` from the same virtual environment.

## Dashboard pages (your Stitch designs, wired to live data)

| Page | URL | What it shows / does |
|---|---|---|
| Overview & Journeys | `/` | Live bar (last checked, chaos mode, auto-sync toggle, **Run probe now**), KPIs (journeys healthy, MTTD, MTTR, ₹ impact), journey cards incl. auto-created ones, Chart.js latency chart with 3 s threshold, failure-by-layer cards + bar chart, root-cause banner, RBI watchdog queue with live countdowns, customer notices (approve/edit/dismiss), recent incidents |
| Active Incidents | `/incidents` | Filterable incident table (active / resolved / all), impact, suggested fix with "Worked N of M", MTTD/MTTR, report links |
| Incident detail | `/incident?id=N` | Evidence screenshot (click to enlarge), step waterfall, bank log lines, RCA (layer, cause, similar incident, AI/rule explanation), pattern insight, **Approve Recovery** (confirm dialog: *Human approval required*), optional fix for manual causes, re-send alert, dismiss, lifecycle timeline, customer notice, report view/download |
| Chaos Control Deck | `/chaos` | All 8 chaos modes + reset, arming switch, trip switch, probe step matrix, E2E sparkline, live engine event terminal |
| Auto-Generated Tests | `/tests` | All journeys with `Auto-created` badges, search/filter, list/grid view, Run now, pause/resume, edit payload, generated script + JSON payload inspector, export suites |
| RBI Watchdog | `/watchdog` | Every debited-not-credited txn with ticking countdown, status, penalty exposure, Reverse / Reverse all |

Header: nav, live probe status, ⚠ button (jumps to latest open incident), 🔔 alert feed with unread badge,
approver menu (name recorded on approvals, links to the mock bank and API docs). Toasts appear bottom-right for
every new alert ("Slack alert sent" or "Alert logged (Slack not configured)").

## Architecture

```
run.py ─┬─ bank (FastAPI :8001)      login → dashboard → transfer → /api/pay → receipt, chaos modes,
        │                            recovery endpoint, request logging → logs/bank.log + bank_logs
        └─ monitor (FastAPI :8000)   dashboard pages + JSON API
              ├─ probe thread        Playwright Chromium walks the journey every 30 s (own Proactor loop)
              └─ engine thread       simulator (2 s) · pattern engine (10 s) · RBI watchdog (15 s)
shared: data/sentinel.db (SQLite, WAL, one connection per operation)
```

Flow: probe → `runs` → detector (false-alarm guard, slow / intermittent / early warning) → incident → RCA (layer,
cause, similar incident, fix + learned success rate) → alert + draft notice → human clicks **Approve** → bank
recovery endpoint → next probe passes → resolved, MTTR recorded, fix outcome learned, report generated.

## Innovations (all visible in the UI)

1. **Self-expanding tests** – a new real-transaction failure pattern (e.g. all failures are to Bank X, or above
   ₹50,000) creates and schedules a synthetic test for that exact case (`/tests`, `Auto-created` badge).
2. **RBI deadline watchdog** – debited-not-credited transactions with live countdowns, warning/breached states and
   penalty exposure; bulk reversal.
3. **Business impact in ₹** – failed value and affected customers per incident and overall (Indian number format, lakh).
4. **Layer-wise root cause** – customer network, bank server, payment gateway, receiver bank.
5. **False-alarm protection** – probe self-check + bank health check; retries; incident only if 2 of 3 attempts fail;
   bank unreachable is treated as a probe/network error until it happens 3 cycles in a row.
6. **Early warning** – latency rising 3 runs in a row and above 70 % of the slow threshold → amber warning.
7. **Auto customer notice** – drafted for gateway / receiver-bank incidents; approved banners show on the bank site
   until the incident resolves.
8. **Auto incident report** – plain-language Markdown on resolution (view + download).
9. **Learns which fix works** – fix outcomes per cause are recorded; "Worked N of M times" next to every suggestion.

## Demo script

1. Open `/` – all green; point at KPIs, seeded history and the RBI watchdog.
2. `/chaos` → **Inject: Gateway Down**.
3. Within ~10–40 s: UPI Payment red, toast, incident with screenshot, layer *Payment gateway*, similar incident,
   ₹ impact, draft customer notice (`/incident?id=…`).
4. Approve the customer notice → open http://127.0.0.1:8001 → banner is live.
5. **Approve recovery action** → confirm → next probe passes → resolved; MTTD/MTTR shown; **View report**.
6. `/chaos` → **Fail Above ₹50,000** → after ~1–2 min the pattern appears and `/tests` gains
   "Transfer above ₹50,000". (Faster alternative: **Receiver Bank Down** → "Transfer to Bank X" in ~30 s.)
7. `/chaos` → **Gateway Timeout** → `/watchdog` fills with countdowns → **Reverse all at risk**.
8. Close: *"Detected in seconds, explained by layer, fixed with one human click."*

## Configuration (`.env`, all optional – see `.env.example`)

| Variable | Default | Purpose |
|---|---|---|
| `PROBE_INTERVAL_SEC` | 30 | Probe cycle |
| `SLOW_THRESHOLD_MS` | 3000 | Slow step threshold |
| `STEP_TIMEOUT_MS` | 6000 | Playwright step timeout |
| `DEMO_MODE` | true | Short RBI deadlines (1 demo-minute late = 1 day of penalty) |
| `DEMO_DEADLINE_MINUTES` | 10 | Deadline in demo mode (T+1 day when `DEMO_MODE=false`) |
| `PENALTY_PER_DAY` | 100 | ₹ per day late |
| `SLACK_WEBHOOK_URL` | – | Slack incoming webhook; otherwise alerts are in-app + console |
| `GEMINI_API_KEY` | – | Optional 2-sentence AI explanation (`GEMINI_MODEL`, default `gemini-2.0-flash`) |
| `BANK_URL` / `MONITOR_URL` | `http://127.0.0.1:8001` / `:8000` | Service URLs (127.0.0.1 avoids IPv6 `localhost` clashes) |

## Decisions and deviations (where the spec was open)

- **Frontend:** the supplied Stitch designs (Inter + JetBrains Mono, cyan/teal palette from `DESIGN.md`) are used
  instead of the spec's single-page Nunito/DM Sans layout. The 4 designed screens became pages, plus an incidents list
  and a full RBI watchdog page; every button and icon in the designs is wired to a real action or replaced by one
  (e.g. "Escalate to NPCI" → *Re-send alert*, traffic-diversion slider removed because the mock bank has no partial failover).
- **Extra dependency:** `python-multipart` (FastAPI needs it for the login form).
- **Mock bank** uses a small inline stylesheet instead of Tailwind CDN so pages are fast, work offline and failure
  screenshots look right; the probe blocks any non-local requests so timings measure only the bank.
- **One incident per root cause:** besides one open incident per journey + step, failures with the same cause on other
  journeys (e.g. an auto-created test) are folded into the existing incident instead of opening duplicates.
- **Pattern rule:** a pattern needs ≥ 5 non-network failures in 2 min; it is pinned to a bank or amount bucket only
  if that slice fails ≥ 60 % while the rest of traffic fails < 10 % (with enough comparison traffic). Rates are
  measured since the failures began, so healthy traffic just before a fault does not dilute them.
- **Intermittent:** confirmed failures whose retries partly pass, or ≥ 2 of the last 5 runs failing with a fail→pass
  recovery in between (even if the latest run passed), are labelled intermittent.
- **Auto-close:** incidents whose condition clears without any recovery action (e.g. chaos reset from the deck) close
  after 3 consecutive green runs (10 for intermittent) as "auto-closed"; no fix outcome or MTTR is recorded for them.
  Recovery actions themselves only ever run from the Approve endpoint.
- **Probe runs the full journey once per cycle**; core journeys own the steps they cover (Login → `login`, etc.).
  Steps after a failure are recorded as `skipped` so dependent journeys show as *blocked*.
- **Limit/risk rule incidents** have no automatic fix ("Review limit/risk rule with operations"); the UI offers the
  optional *Restart payment service* action, which also needs approval.

## Safety and non-goals

No real money, banks or customer data: every transaction is simulated, probe transactions are tagged
`synthetic=1` and excluded from impact. Test credentials only (`demo` / `demo123`) on localhost. Deadlines and
compensation are configurable and based on RBI TAT guidelines for failed transactions; verify against current RBI
circulars – not legal advice.

**Future work:** dashboard authentication and role-based approval, persistent chaos/probe state across restarts,
real gateway/CBS integrations, multi-region probes.
