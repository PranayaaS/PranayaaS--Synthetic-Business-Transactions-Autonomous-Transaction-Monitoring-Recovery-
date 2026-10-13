"""Wipe the database, screenshots and bank log, then reseed for a clean demo. Stop run.py first."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from common import config, db  # noqa: E402

for suffix in ("", "-wal", "-shm"):
    p = Path(str(config.DB_PATH) + suffix)
    try:
        p.unlink(missing_ok=True)
    except PermissionError:
        sys.exit("Database is in use – stop run.py before resetting.")
for f in config.SHOT_DIR.glob("*.png"):
    f.unlink(missing_ok=True)
(config.LOG_DIR / "bank.log").write_text("", encoding="utf-8")

db.init_schema()
db.seed()
print("Database reset and reseeded:", config.DB_PATH)
