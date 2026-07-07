"""
Replit startup script for ChainMind Network.
Runs both the FastAPI node server (port 8000) and Streamlit dashboard (port 5000).
"""
import os
import sys
import subprocess
import signal
import time
from pathlib import Path

ROOT = Path(__file__).parent
os.environ["CHAINMIND_CONFIG"] = str(ROOT / "config.yaml")
os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
os.environ.setdefault("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")

processes = []


def cleanup(signum=None, frame=None):
    for p in processes:
        try:
            p.terminate()
        except Exception:
            pass
    sys.exit(0)


signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)

server_proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "node.server:app",
     "--host", "localhost", "--port", "8000"],
    cwd=str(ROOT),
)
processes.append(server_proc)

time.sleep(2)

dashboard_proc = subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run",
     str(ROOT / "node" / "dashboard.py"),
     "--server.port", "5000",
     "--server.address", "0.0.0.0",
     "--server.headless", "true",
     "--server.enableCORS", "false",
     "--server.enableXsrfProtection", "false",
     "--browser.gatherUsageStats", "false",
     "--global.developmentMode", "false",
     ],
    cwd=str(ROOT),
)
processes.append(dashboard_proc)

while True:
    if server_proc.poll() is not None:
        print("FastAPI server exited, restarting...")
        server_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "node.server:app",
             "--host", "localhost", "--port", "8000"],
            cwd=str(ROOT),
        )
        processes[0] = server_proc

    if dashboard_proc.poll() is not None:
        print("Dashboard exited.")
        break

    time.sleep(5)
