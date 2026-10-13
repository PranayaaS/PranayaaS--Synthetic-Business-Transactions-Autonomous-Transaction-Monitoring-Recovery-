"""Start SentinelPay: initialise + seed the DB, then run the mock bank (8001) and monitor (8000)."""
import multiprocessing
import os
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def _bind(family, host, port):
    s = socket.socket(family, socket.SOCK_STREAM)
    if family == socket.AF_INET6:
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    s.bind((host, port))
    s.listen(2048)
    s.set_inheritable(True)
    return s


def serve(app_path, port):
    """Listen on IPv4 and IPv6 loopback so http://localhost:<port> works whichever one the browser picks."""
    sys.path.insert(0, str(ROOT))
    import uvicorn
    sockets = [_bind(socket.AF_INET, "127.0.0.1", port)]
    try:
        sockets.append(_bind(socket.AF_INET6, "::1", port))
    except OSError as e:
        print(f"[run.py] IPv6 localhost unavailable on port {port} ({e}); serving on 127.0.0.1 only.")
    server = uvicorn.Server(uvicorn.Config(app_path, log_level="warning"))
    server.run(sockets=sockets)


def main():
    from common import config, db
    db.init_schema()
    if db.seed_if_empty():
        print("Database seeded with demo history.")

    bank = multiprocessing.Process(target=serve, args=("bank.app:app", 8001), name="bank", daemon=True)
    bank.start()
    time.sleep(1.5)
    monitor = multiprocessing.Process(target=serve, args=("monitor.app:app", 8000), name="monitor", daemon=True)
    monitor.start()
    time.sleep(2)
    print("\nSentinelPay running")
    print("  Dashboard : http://localhost:8000")
    print("  Mock bank : http://localhost:8001   (login: demo / demo123)")
    print(f"  Slack     : {'webhook configured' if config.SLACK_WEBHOOK_URL else 'not configured (alerts shown in-app)'}")
    print(f"  Gemini    : {'enabled' if config.GEMINI_API_KEY else 'not configured (rule-based RCA only)'}")
    print("Press Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1)
            for p in (bank, monitor):
                if not p.is_alive():
                    print(f"[run.py] {p.name} process exited (code {p.exitcode}).")
                    if p is monitor:
                        return
                    # The bank stopping is a supported scenario (acceptance check 12): keep the monitor up.
                    bank = None if p is bank else bank
            if bank is None:
                while monitor.is_alive():
                    time.sleep(1)
                return
    except KeyboardInterrupt:
        print("\nStopping SentinelPay...")
    finally:
        for p in (bank, monitor):
            if p is not None and p.is_alive():
                p.terminate()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
