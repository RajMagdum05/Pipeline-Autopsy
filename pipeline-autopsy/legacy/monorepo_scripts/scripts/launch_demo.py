"""
Pipeline Autopsy — Application Launcher
========================================
Starts the backend services (Autopsy Core & Enterprise Pipeline)
and launches the React 19 Application directly in your browser (http://localhost:5173).
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

# Safe Windows console encoding and line buffering
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT_DIR = Path(__file__).resolve().parents[1]
PID_FILE = ROOT_DIR / "scripts" / "demo_pids.json"


def find_python():
    autopsy_py = ROOT_DIR / "autopsy" / ".venv" / "Scripts" / "python.exe"
    if not autopsy_py.exists():
        autopsy_py = Path(sys.executable)

    pipeline_py = ROOT_DIR / "enterprise-pipeline" / ".venv" / "Scripts" / "python.exe"
    if not pipeline_py.exists():
        pipeline_py = Path(sys.executable)

    return str(autopsy_py), str(pipeline_py)


def is_service_ready(url: str, timeout: float = 1.0) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "HealthCheck/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 304)
    except Exception:
        return False


def kill_existing_on_ports(ports=(8080, 8000, 5173, 3000)):
    if os.name == "nt":
        try:
            ports_str = ",".join(str(p) for p in ports)
            cmd = f'powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort {ports_str} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique"'
            res = subprocess.run(cmd, capture_output=True, text=True, shell=True)
            for pid_str in res.stdout.strip().split():
                try:
                    pid = int(pid_str)
                    if pid > 4:
                        subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, capture_output=True)
                except ValueError:
                    pass
        except Exception:
            pass


def main():
    print("\n" + "=" * 76)
    print(" [*] PIPELINE AUTOPSY - APPLICATION LAUNCHER")
    print("=" * 76)

    # 1. Clean existing ports
    print("[1/5] Checking ports and cleaning old processes...")
    kill_existing_on_ports()

    autopsy_py, pipeline_py = find_python()
    procs = {}

    # 2. Launch Autopsy Core Backend (Port 8080)
    print("[2/5] Starting Autopsy Backend Engine (Port 8080)...")
    env_autopsy = os.environ.copy()
    env_autopsy["PYTHONPATH"] = str(ROOT_DIR)
    p_autopsy = subprocess.Popen(
        [autopsy_py, "-m", "uvicorn", "autopsy.main:app", "--host", "127.0.0.1", "--port", "8080"],
        cwd=str(ROOT_DIR),
        env=env_autopsy,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    procs["autopsy"] = p_autopsy.pid

    # 3. Launch Enterprise Claims Pipeline (Port 8000)
    print("[3/5] Starting Enterprise Claims Pipeline (Port 8000)...")
    env_pipeline = os.environ.copy()
    env_pipeline["PYTHONPATH"] = str(ROOT_DIR / "enterprise-pipeline")
    p_pipeline = subprocess.Popen(
        [pipeline_py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(ROOT_DIR / "enterprise-pipeline"),
        env=env_pipeline,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    procs["enterprise_pipeline"] = p_pipeline.pid

    # 4. Launch Static Docs & Marketing Website (Port 3000)
    print("[4/5] Starting Website & Interactive Docs (Port 3000)...")
    website_dir = ROOT_DIR / "website"
    p_website = subprocess.Popen(
        [sys.executable, "-m", "http.server", "3000", "--directory", str(website_dir)],
        cwd=str(website_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    procs["website"] = p_website.pid

    # 5. Launch React Claims Dashboard (Port 5173)
    print("[5/5] Starting Application UI (Port 5173)...")
    frontend_dir = ROOT_DIR / "frontend"
    vite_bin = frontend_dir / "node_modules" / "vite" / "bin" / "vite.js"

    if vite_bin.exists() and shutil.which("node"):
        frontend_cmd = f"node \"{vite_bin}\" --host 127.0.0.1 --port 5173"
    elif shutil.which("npx.cmd"):
        frontend_cmd = "npx.cmd vite --host 127.0.0.1 --port 5173"
    else:
        frontend_cmd = "npm.cmd run dev -- --host 127.0.0.1 --port 5173"

    p_frontend = subprocess.Popen(
        frontend_cmd,
        cwd=str(frontend_dir),
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    procs["frontend"] = p_frontend.pid

    # Save PIDs
    with open(PID_FILE, "w", encoding="utf-8") as f:
        json.dump(procs, f, indent=2)

    # Wait for Application to be ready
    print("\n[..] Waiting for Application to initialize...")
    app_ready = False
    start_wait = time.time()
    while time.time() - start_wait < 15:
        if is_service_ready("http://127.0.0.1:5173"):
            app_ready = True
            break
        time.sleep(0.4)

    print("\n" + "=" * 76)
    if app_ready:
        print(" [OK] APPLICATION IS LIVE AND READY!")
    else:
        print(" [!] APPLICATION STARTED (FINISHING INITIALIZATION)...")
    print("=" * 76)
    print(" >>> OPENING APPLICATION 👉 http://localhost:5173 <<<")
    print("=" * 76)
    print(" [Services Running]:")
    print("  * Forensic Dashboard UI        : http://localhost:5173")
    print("  * Marketing & Interactive Docs : http://localhost:3000")
    print("  * Autopsy Observability Engine : http://localhost:8080/docs")
    print("  * Claims Pipeline API          : http://localhost:8000/docs")
    print("=" * 76)

    # ONLY open the application!
    try:
        webbrowser.open("http://localhost:5173")
    except Exception:
        pass

    print("\n[NOTE] Application is running in the background.")
    print("       Press Ctrl+C in this terminal, or run 'stop_demo.bat' to stop.")
    print("=" * 76 + "\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Shutting down application and backend services...")
        kill_existing_on_ports()
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except Exception:
                pass
        print("[OK] All services stopped cleanly.")


if __name__ == "__main__":
    main()
