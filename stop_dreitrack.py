from __future__ import annotations
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parent
PID_FILE = ROOT / 'logs' / 'dreitrack-server.pid'
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

def stop_server() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text(encoding='utf-8').strip())
    except (OSError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return False
    try:
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, check=False)
    finally:
        PID_FILE.unlink(missing_ok=True)
    return True
if __name__ == '__main__':
    stop_server()
