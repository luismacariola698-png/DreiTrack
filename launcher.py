from __future__ import annotations
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from app.network import load_launcher_settings, network_access_context
ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / 'logs'
SERVER_PID_FILE = LOG_DIR / 'dreitrack-server.pid'
OLLAMA_PID_FILE = LOG_DIR / 'dreitrack-ollama.pid'
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
DETACHED_PROCESS = getattr(subprocess, 'DETACHED_PROCESS', 0)
WINDOW_FLAGS = CREATE_NO_WINDOW | DETACHED_PROCESS

def url_available(url: str, timeout: float=1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False

def find_ollama() -> str | None:
    located = shutil.which('ollama')
    if located:
        return located
    candidates = [Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Ollama' / 'ollama.exe', Path(os.environ.get('USERPROFILE', '')) / 'AppData' / 'Local' / 'Programs' / 'Ollama' / 'ollama.exe']
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None

def spawn_hidden(command: list[str], log_name: str) -> subprocess.Popen:
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / log_name
    log_handle = open(log_path, 'a', encoding='utf-8')
    return subprocess.Popen(command, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log_handle, stderr=log_handle, creationflags=WINDOW_FLAGS, close_fds=True)

def ensure_ollama() -> None:
    if url_available('http://127.0.0.1:11434/api/tags'):
        return
    executable = find_ollama()
    if executable is None:
        return
    process = spawn_hidden([executable, 'serve'], 'ollama.log')
    OLLAMA_PID_FILE.write_text(str(process.pid), encoding='utf-8')
    for _ in range(20):
        if url_available('http://127.0.0.1:11434/api/tags'):
            return
        time.sleep(0.5)

def ensure_server(host: str, port: int) -> None:
    local_url = f'http://127.0.0.1:{port}/login'
    if url_available(local_url):
        return
    command = [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', str(host), '--port', str(port), '--log-level', 'info']
    process = spawn_hidden(command, 'server.log')
    SERVER_PID_FILE.write_text(str(process.pid), encoding='utf-8')
    for _ in range(40):
        if url_available(local_url):
            return
        if process.poll() is not None:
            raise RuntimeError('DreiTrack stopped while starting. Check logs/server.log for details.')
        time.sleep(0.5)
    raise RuntimeError('DreiTrack did not become available within 20 seconds.')

def write_network_info() -> None:
    info = network_access_context()
    LOG_DIR.mkdir(exist_ok=True)
    lines = ['DreiTrack private network information', f"Mode: {('LAN enabled' if info['enabled'] else 'Local computer only')}", f"Server computer: {info['hostname']}", f"Port: {info['port']}", f"Local URL: {info['local_url']}"]
    if info['enabled']:
        lines.append('Private network URLs:')
        lines.extend((f'- {url}' for url in info['urls']))
    else:
        lines.append('Run Enable Private Network Access.bat once to allow approved computers on the private LAN.')
    (LOG_DIR / 'network-info.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    settings = load_launcher_settings()
    port = int(settings.get('port', 8000))
    host = str(settings.get('host', '127.0.0.1'))
    if bool(settings.get('start_ollama', True)):
        ensure_ollama()
    ensure_server(host, port)
    write_network_info()
    if bool(settings.get('open_browser', True)) and (not args.no_browser):
        webbrowser.open(f'http://localhost:{port}')
    return 0
if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOG_DIR.mkdir(exist_ok=True)
        (LOG_DIR / 'launcher-error.log').write_text(str(exc), encoding='utf-8')
        raise
