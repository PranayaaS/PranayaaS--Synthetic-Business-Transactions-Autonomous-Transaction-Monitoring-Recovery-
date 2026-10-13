"""Shared HTTP clients. Creating an httpx client costs ~0.5 s (TLS setup), so clients are reused."""
import threading

import httpx

_lock = threading.Lock()
_sync = None


def client():
    """Thread-safe shared sync client for local service calls."""
    global _sync
    with _lock:
        if _sync is None:
            _sync = httpx.Client(timeout=5, trust_env=False)
        return _sync
