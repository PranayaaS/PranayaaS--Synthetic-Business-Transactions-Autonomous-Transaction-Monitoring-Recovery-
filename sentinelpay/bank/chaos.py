"""In-memory chaos state for the mock bank (demo fault injection)."""
import threading

from common.db import iso

MODES = {
    "none": "Normal operation",
    "gateway_down": "Payment gateway returns HTTP 502",
    "gateway_timeout": "Payment gateway hangs for 8 s",
    "slow_gateway": "Payment gateway latency ramps 2.5 s -> 3.5 s",
    "wrong_amount": "Receipt shows amount + 1",
    "server_error": "Login returns HTTP 500",
    "receiver_bank_down": "Payments to Bank X return 503 RB_UNAVAILABLE",
    "large_amount_fail": "Payments above Rs 50,000 return 422 LIMIT_OR_RISK_CHECK",
    "intermittent": "40% of payments fail with HTTP 502",
}

# Which chaos modes each recovery action clears.
RECOVERY_CLEARS = {
    "switch_backup_gateway": {"gateway_down", "gateway_timeout", "slow_gateway", "intermittent"},
    "restart_payment_service": {"server_error", "large_amount_fail"},
    "rollback_receipt_service": {"wrong_amount"},
    "pause_receiver_bank": {"receiver_bank_down"},
}

_lock = threading.Lock()
_state = {"mode": "none", "activated_at": None, "paused_banks": set(), "pay_calls": 0}


def get():
    with _lock:
        return {
            "mode": _state["mode"],
            "description": MODES[_state["mode"]],
            "activated_at": _state["activated_at"],
            "paused_banks": sorted(_state["paused_banks"]),
            "modes": MODES,
        }


def set_mode(mode):
    if mode not in MODES:
        raise ValueError(mode)
    with _lock:
        _state["mode"] = mode
        _state["activated_at"] = iso() if mode != "none" else None
        _state["pay_calls"] = 0
        _state["paused_banks"].clear()  # every new scenario (or reset) starts with no paused banks
    return get()


def mode():
    return _state["mode"]


def next_pay_call():
    with _lock:
        _state["pay_calls"] += 1
        return _state["pay_calls"]


def is_paused(bank):
    return bank in _state["paused_banks"]


def recover(action):
    """Apply a recovery action. Returns (cleared: bool, message)."""
    if action not in RECOVERY_CLEARS:
        raise ValueError(action)
    with _lock:
        cleared = _state["mode"] in RECOVERY_CLEARS[action]
        if cleared:
            _state["mode"] = "none"
            _state["activated_at"] = None
            _state["pay_calls"] = 0
        if action == "pause_receiver_bank":
            _state["paused_banks"].add("Bank X")
    msg = "fault cleared" if cleared else "no matching fault for this action"
    return cleared, msg
