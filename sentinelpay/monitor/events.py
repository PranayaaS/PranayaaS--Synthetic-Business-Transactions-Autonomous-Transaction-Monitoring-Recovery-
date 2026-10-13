"""In-memory engine event feed (shown in the Chaos Control Deck terminal)."""
import itertools
import threading
from collections import deque

from common.db import iso

_lock = threading.Lock()
_events = deque(maxlen=400)
_ids = itertools.count(1)


def emit(level, tag, message):
    """level: info | warn | crit | ok | audit"""
    with _lock:
        _events.append({"id": next(_ids), "ts": iso(), "level": level, "tag": tag, "message": message})
    print(f"[{tag}] {message}", flush=True)


def since(event_id=0, limit=200):
    with _lock:
        return [e for e in _events if e["id"] > event_id][-limit:]
