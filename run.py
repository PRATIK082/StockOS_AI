"""One-command startup for StockOS AI (backend + frontend).

Usage:
    py .\\run.py

The backend MUST run with the project virtual environment
(``backend/.venv``) because it owns the pinned dependencies
(FastAPI, SQLAlchemy, slowapi, duckdb, tradingagents, ...). Launching it
with the system interpreter fails with errors such as
``ModuleNotFoundError: No module named 'slowapi'``.

This script therefore:
  1. Locates the project virtualenv interpreter.
  2. Preflights the backend imports and reports a clear, actionable error
     if the environment is not ready.
  3. Starts uvicorn (hot reload) and the Next.js dev server on the
     configured ports, resolving paths relative to this file so the
     script works from any CWD.
  4. Never steals ports: if a port is already in use (for example a
     previous ``run.py`` is still running), the existing service is
     reused and is left alone on shutdown. Only processes started by
     this script are terminated on Ctrl+C.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "3000"))


def find_backend_python() -> str | None:
    """Return the interpreter of the project virtualenv, if it exists."""
    candidates = [
        BACKEND / ".venv" / "Scripts" / "python.exe",  # Windows
        BACKEND / ".venv" / "bin" / "python",  # POSIX
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def is_port_in_use(port: int) -> bool:
    """True when something is already listening on ``port`` (IPv4 or IPv6).

    Next.js listens on ``::`` (IPv6 any), which does not always accept
    IPv4-mapped connections on Windows, so both loopbacks are probed.
    """
    for family, host in (
        (socket.AF_INET, "127.0.0.1"),
        (socket.AF_INET6, "::1"),
    ):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.0)
                if sock.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def preflight_backend(python: str) -> bool:
    """Import the FastAPI app to fail fast with a readable message."""
    code = "import app.main; print('backend-import-ok')"
    try:
        result = subprocess.run(
            [python, "-c", code],
            cwd=str(BACKEND),
            capture_output=True,
            text=True,
        )
    except OSError as exc:  # pragma: no cover - defensive
        print(f"[!] Could not run backend interpreter: {exc}")
        return False

    if result.returncode != 0:
        print("[!] Backend dependencies are not installed in the virtualenv.")
        tail = (result.stderr or "").strip().splitlines()[-12:]
        for line in tail:
            print(f"    {line}")
        print("\n    Fix it with:")
        print(f"      {python} -m pip install -e .")
        print("    (or: cd backend && uv sync)")
        return False

    print("[OK] Backend dependencies verified.")
    return True


def wait_for_http(url: str, timeout: float = 60.0) -> bool:
    """Poll ``url`` until it answers or ``timeout`` seconds pass."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status < 500:
                    return True
        except OSError:
            time.sleep(1.0)
    return False


def start_backend(python: str) -> subprocess.Popen | None:
    if is_port_in_use(BACKEND_PORT):
        print(
            f"[*] Port {BACKEND_PORT} is already in use - reusing the running "
            "backend instead of starting a second one."
        )
        print(f"    API Docs: http://localhost:{BACKEND_PORT}/docs")
        return None
    print("Starting backend server...")
    return subprocess.Popen(
        [
            python,
            "-m",
            "uvicorn",
            "app.main:app",
            "--reload",
            "--port",
            str(BACKEND_PORT),
        ],
        cwd=str(BACKEND),
    )


def start_frontend() -> subprocess.Popen | None:
    if is_port_in_use(FRONTEND_PORT):
        print(
            f"[*] Port {FRONTEND_PORT} is already in use - reusing the running "
            "frontend instead of starting a second one."
        )
        print(f"    Frontend: http://localhost:{FRONTEND_PORT}")
        return None
    print("Starting frontend server...")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    return subprocess.Popen(
        [npm, "run", "dev", "--", "-p", str(FRONTEND_PORT)],
        cwd=str(FRONTEND),
    )


def main() -> int:
    print("=" * 50)
    print("StockOS AI - Starting Services")
    print("=" * 50)

    python = find_backend_python()
    if python is None:
        print("[!] Virtualenv not found at backend/.venv")
        print("    Create it with:  cd backend && uv sync")
        print("    or:              py -3.12 -m venv backend\\.venv")
        return 1
    print(f"Using backend interpreter: {python}")

    if not preflight_backend(python):
        return 1

    backend = start_backend(python)
    if backend is None:
        print(f"Backend already running on http://localhost:{BACKEND_PORT}")
    else:
        print(f"Backend starting on http://localhost:{BACKEND_PORT}")
        print(f"API Docs: http://localhost:{BACKEND_PORT}/docs")

    if not wait_for_http(f"http://localhost:{BACKEND_PORT}/docs", timeout=60.0):
        print(f"[!] Backend did not answer on port {BACKEND_PORT} within 60s.")
        print("    Check the backend output above for the real error")
        print("    (a stale process holding the port is the usual cause).")
        if backend is not None and backend.poll() is None:
            backend.terminate()
        return 1

    frontend = start_frontend()
    if frontend is None:
        print(f"Frontend already running on http://localhost:{FRONTEND_PORT}")
    else:
        print(f"Frontend starting on http://localhost:{FRONTEND_PORT}")

    owned = [p for p in (backend, frontend) if p is not None]
    print("\n" + "=" * 50)
    if owned:
        print("Services are starting...")
    else:
        print("Both services were already running - nothing new started.")
    print("Press Ctrl+C to stop services started by this script")
    print("(already-running services are left untouched)")
    print("=" * 50)

    try:
        while True:
            time.sleep(1)
            for proc in owned:
                if proc.poll() is not None:
                    print(f"[!] A service started by this script exited (code {proc.returncode}).")
                    print("    See its output above. Already-running services were left alone.")
                    return 1
    except KeyboardInterrupt:
        print("\nShutting down services started by this script...")
        for proc in owned:
            if proc.poll() is None:
                proc.terminate()
        print("Shutdown complete! (already-running services were left untouched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
