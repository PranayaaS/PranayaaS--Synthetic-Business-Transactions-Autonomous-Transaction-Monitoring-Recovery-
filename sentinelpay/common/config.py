"""Configuration loaded from .env (optional) with safe defaults."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional at runtime
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent
if load_dotenv:
    load_dotenv(ROOT / ".env")


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name, default):
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


PROBE_INTERVAL_SEC = _int("PROBE_INTERVAL_SEC", 30)
SLOW_THRESHOLD_MS = _int("SLOW_THRESHOLD_MS", 3000)
STEP_TIMEOUT_MS = _int("STEP_TIMEOUT_MS", 6000)
DEMO_MODE = _bool("DEMO_MODE", True)
DEMO_DEADLINE_MINUTES = _int("DEMO_DEADLINE_MINUTES", 10)
PENALTY_PER_DAY = _int("PENALTY_PER_DAY", 100)
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
BANK_URL = os.getenv("BANK_URL", "http://127.0.0.1:8001").rstrip("/")
MONITOR_URL = os.getenv("MONITOR_URL", "http://127.0.0.1:8000").rstrip("/")

# Early warning fires when latency rises 3 runs in a row and exceeds this share of the slow threshold.
EARLY_WARNING_RATIO = 0.7

DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
SHOT_DIR = ROOT / "screenshots"
DB_PATH = DATA_DIR / "sentinel.db"

for _d in (DATA_DIR, LOG_DIR, SHOT_DIR):
    _d.mkdir(parents=True, exist_ok=True)
