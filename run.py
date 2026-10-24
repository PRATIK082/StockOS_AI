"""Simple startup script for StockOS AI"""
import subprocess
import time
import sys
import os

def start_backend():
    """Start the backend server"""
    print("Starting backend server...")
    backend_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"],
        cwd="backend",
        shell=True
    )
    return backend_process

def start_frontend():
    """Start the frontend server"""
    print("Starting frontend server...")
    frontend_process = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd="frontend",
        shell=True
    )
    return frontend_process

def main():
    print("=" * 50)
    print("StockOS AI - Starting Services")
    print("=" * 50)
    
    # Start backend
    backend = start_backend()
    print("Backend starting on http://localhost:8000")
    print("API Docs: http://localhost:8000/docs")
    
    # Wait for backend to start
    time.sleep(5)
    
    # Start frontend
    frontend = start_frontend()
    print("Frontend starting on http://localhost:3000")
    
    print("\n" + "=" * 50)
    print("Services are starting...")
    print("Press Ctrl+C to stop all services")
    print("=" * 50)
    
    try:
        # Keep running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down services...")
        backend.terminate()
        frontend.terminate()
        print("Shutdown complete!")

if __name__ == "__main__":
    main()