"""One-command startup for StockOS AI (backend + frontend).

Usage:
    py .\run.py

The backend MUST run with the project virtual environment
(``backend/.venv``) because it owns the pinned dependencies
(FastAPI, SQLAlchemy, slowapi, duckdb, tradingagents, ...). Launching it
with the system interpreter fails with errors such as
``ModuleNotFoundError: No module named 'slowapi'``.

This script therefore:
  1. Locates the project virtualenv interpreter.
  2. Preflights the backend imports and reports a clear, actionable error
     if the environment is not ready.
  3. Starts uvicorn (hot reload) and the Next.js dev server, resolving
     paths relative to this file so the script works from any CWD.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
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


def start_backend(python: str) -> subprocess.Popen:
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


def start_frontend() -> subprocess.Popen:
    print("Starting frontend server...")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    return subprocess.Popen([npm, "run", "dev"], cwd=str(FRONTEND))


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
    print(f"Backend starting on http://localhost:{BACKEND_PORT}")
    print(f"API Docs: http://localhost:{BACKEND_PORT}/docs")

    time.sleep(5)

    frontend = start_frontend()
    print(f"Frontend starting on http://localhost:{FRONTEND_PORT}")

    print("\n" + "=" * 50)
    print("Services are starting...")
    print("Press Ctrl+C to stop all services")
    print("=" * 50)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down services...")
        for proc in (backend, frontend):
            if proc and proc.poll() is None:
                proc.terminate()
        print("Shutdown complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
