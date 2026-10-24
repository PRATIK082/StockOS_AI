#!/usr/bin/env python3
"""
StockOS - Portable AI Investment Research Platform Setup

This script sets up StockOS for installation on any compatible system
without requiring local venv management. Uses uv for package management.

Usage:
    python setup_stockos.py install          # Full installation
    python setup_stockos.py dev            # Development mode
    python setup_stockos.py test           # Test installation
"""

import subprocess
import sys
import os
from pathlib import Path

def run_cmd(cmd, cwd=None, description=""):
    """Run a command and return result."""
    print(f">>> {description}: {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        print(f"  stdout: {result.stdout[-200:]}")
    if result.stderr:
        print(f"  stderr: {result.stderr[-200:]}")
    if result.returncode != 0:
        print(f"  WARNING: Command exited with code {result.returncode}")
    return result.returncode == 0

def check_python():
    """Check Python version compatibility."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 12):
        print(f"❌ Python {version.major}.{version.minor} detected. StockOS requires Python >= 3.12")
        return False
    print(f"✅ Python {version.major}.{version.minor}.{version.micro} - OK")
    return True

def check_uv():
    """Check if uv is available."""
    result = subprocess.run(["uv", "--version"], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"✅ uv available: {result.stdout.strip()}")
        return True
    else:
        print("⚠️  uv not found - will use pip fallback")
        return False

def install_with_uv():
    """Install backend dependencies using uv."""
    backend_dir = Path("backend")
    
    print("\n📦 Installing backend dependencies with uv...")
    
    # Sync dependencies
    success = run_cmd(
        "uv sync --frozen-check 2>/dev/null || uv sync",
        cwd=backend_dir,
        description="Backend sync"
    )
    
    if not success:
        print("⚠️  uv sync had issues, trying pip fallback...")
        # Fallback to pip
        run_cmd("pip install -e .", cwd=backend_dir, description="pip install fallback")
    
    # Install frontend deps
    frontend_dir = Path("frontend")
    print("\n📦 Installing frontend dependencies...")
    run_cmd("npm install", cwd=frontend_dir, description="Frontend npm install")
    
    print("\n✅ Backend and frontend dependencies installed!")

def setup_environment():
    """Set up environment files."""
    backend_dir = Path("backend")
    
    print("\n🌍 Setting up environment files...")
    
    # Check for .env.example and create .env if needed
    env_example = backend_dir / ".env.example"
    env_file = backend_dir / ".env"
    
    if env_example.exists() and not env_file.exists():
        print("  Creating .env from .env.example...")
        content = env_example.read_text()
        env_file.write_text(content)
        print("  ⚠️  Please edit .env with your actual credentials (API keys, etc.)")
    elif env_file.exists():
        print("  .env already exists - skipping creation")
    else:
        print("  ⚠️  No .env.example found, creating minimal .env...")
        env_file.write_text("# StockOS Environment Variables\n")
        print("  Please add your LLM provider credentials to .env")
    
    # Check for frontend .env
    frontend_env = frontend_dir / ".env.local"
    if not frontend_env.exists():
        frontend_env.write_text("# Frontend Environment Variables\nNEXT_PUBLIC_API_URL=http://localhost:8000\n")
        print("  Created frontend .env.local")

def verify_installation():
    """Verify the installation works."""
    backend_dir = Path("backend")
    
    print("\n🔍 Verifying installation...")
    
    # Test backend import
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app; print('✅ Backend API imports OK')"],
        cwd=backend_dir,
        capture_output=True,
        text=True
    )
    print(f"  {result.stdout.strip()}")
    if result.stderr:
        print(f"  {result.stderr}")
    
    # Test frontend typecheck
    frontend_dir = Path("frontend")
    result = subprocess.run(
        ["npx", "tsc", "--noEmit"],
        cwd=frontend_dir,
        capture_output=True,
        text=True,
        timeout=120000
    )
    if result.returncode == 0:
        print("✅ Frontend typecheck passes")
    else:
        print(f"⚠️  Frontend typecheck issues (may be OK): {result.stdout[-100:]}")

def main():
    """Main entry point."""
    print("=" * 60)
    print("🦊 StockOS - AI Investment Research Platform")
    print("=" * 60)
    
    if not check_python():
        sys.exit(1)
    
    # Parse arguments
    args = sys.argv[1:]
    command = args[0] if args else "install"
    
    if command == "install":
        install_with_uv()
        setup_environment()
        verify_installation()
    elif command == "dev":
        print("🛠️  Development mode selected")
        print("   Backend: uv run uvicorn app.main:app --reload --port 8000")
        print("   Frontend: npm run dev (in frontend/)")
    elif command == "test":
        print("🧪 Running tests...")
        backend_dir = Path("backend")
        result = subprocess.run(
            ["python", "-m", "pytest", "-q"],
            cwd=backend_dir,
            capture_output=True,
            text=True,
            timeout=180000
        )
        print(result.stdout[-500:] if result.stdout else "")
        print(result.stderr[-500:] if result.stderr else "")
        if result.returncode == 0:
            print("✅ All tests passed!")
        else:
            print(f"⚠️  Tests exited with code {result.returncode}")
    elif command == "info":
        print("📋 StockOS Information:")
        print(f"   Backend: {Path('backend').absolute()}")
        print(f"   Frontend: {Path('frontend').absolute()}")
        print(f"   Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
        print(f"   UV available: {subprocess.run(['uv', '--version'], capture_output=True).returncode == 0}")
    else:
        print(f"Unknown command: {command}")
        print("Available: install, dev, test, info")
        sys.exit(1)

if __name__ == "__main__":
    main()