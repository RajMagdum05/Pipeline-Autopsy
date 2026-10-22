"""
Clean shutdown script for Pipeline Autopsy presentation services.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

# Safe Windows console encoding and immediate line buffering
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT_DIR = Path(__file__).resolve().parents[1]
PID_FILE = ROOT_DIR / "scripts" / "demo_pids.json"


def kill_ports(ports=(8080, 8000, 5173, 3000)):
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
    print("=" * 60)
    print(" [*] STOPPING PIPELINE AUTOPSY DEMO SERVICES")
    print("=" * 60)

    if PID_FILE.exists():
        try:
            with open(PID_FILE, "r", encoding="utf-8") as f:
                pids = json.load(f)
                for name, pid in pids.items():
                    print(f"Terminating {name} (PID {pid})...")
                    subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, capture_output=True)
            PID_FILE.unlink()
        except Exception as e:
            print(f"Note: {e}")

    # Fallback cleanup on exact ports
    kill_ports()
    print("[OK] All demo services (8080, 8000, 5173, 3000) stopped.")
    print("=" * 60)


if __name__ == "__main__":
    main()
