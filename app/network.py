from __future__ import annotations
import ipaddress
import json
import socket
from pathlib import Path
from urllib.parse import urlsplit
ROOT = Path(__file__).resolve().parent.parent
LAUNCHER_SETTINGS_FILE = ROOT / 'launcher_settings.json'
ALLOWED_PRIVATE_NETWORKS = tuple((ipaddress.ip_network(value) for value in ('127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16', '::1/128', 'fc00::/7', 'fe80::/10')))

def load_launcher_settings() -> dict:
    defaults = {'host': '127.0.0.1', 'port': 8000, 'open_browser': True, 'start_ollama': True}
    if not LAUNCHER_SETTINGS_FILE.exists():
        return defaults
    try:
        loaded = json.loads(LAUNCHER_SETTINGS_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return defaults
    for key in defaults:
        if key in loaded:
            defaults[key] = loaded[key]
    return defaults

def server_hostname() -> str:
    try:
        return socket.gethostname().strip() or 'DreiTrack-Server'
    except OSError:
        return 'DreiTrack-Server'

def private_ipv4_addresses() -> list[str]:
    """Return private IPv4 addresses currently assigned to the server.

    The result is intentionally conservative: loopback and link-local addresses
    are excluded from the LAN list shown to administrators.
    """
    addresses: set[str] = set()
    hostname = server_hostname()
    candidates: list[str] = []
    try:
        _, _, resolved = socket.gethostbyname_ex(hostname)
        candidates.extend(resolved)
    except OSError:
        pass
    try:
        for record in socket.getaddrinfo(hostname, None, family=socket.AF_INET):
            candidates.append(record[4][0])
    except OSError:
        pass
    for value in candidates:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if not isinstance(address, ipaddress.IPv4Address):
            continue
        if address.is_loopback or address.is_link_local:
            continue
        if address.is_private:
            addresses.add(str(address))
    return sorted(addresses, key=lambda value: tuple((int(part) for part in value.split('.'))))

def private_network_enabled() -> bool:
    host = str(load_launcher_settings().get('host', '127.0.0.1')).strip()
    return host in {'0.0.0.0', '::', '[::]'}

def network_access_context() -> dict:
    settings = load_launcher_settings()
    port = int(settings.get('port', 8000))
    hostname = server_hostname()
    addresses = private_ipv4_addresses()
    enabled = private_network_enabled()
    urls = [f'http://{hostname}:{port}']
    urls.extend((f'http://{address}:{port}' for address in addresses))
    urls = list(dict.fromkeys(urls))
    return {'enabled': enabled, 'host': str(settings.get('host', '127.0.0.1')), 'port': port, 'hostname': hostname, 'private_ipv4_addresses': addresses, 'urls': urls, 'local_url': f'http://localhost:{port}'}

def is_allowed_private_client(client_host: str | None) -> bool:
    """Allow loopback/private clients and test/non-IP clients.

    Uvicorn supplies a numeric client IP for real network traffic. A non-IP
    value is allowed so FastAPI's TestClient and future trusted local adapters
    can still function. Public numeric IP addresses are denied.
    """
    if not client_host:
        return True
    try:
        address = ipaddress.ip_address(client_host.split('%', 1)[0])
    except ValueError:
        return True
    return any((address in network for network in ALLOWED_PRIVATE_NETWORKS))

def same_origin_or_local_request(*, host_header: str | None, origin_header: str | None, referer_header: str | None) -> bool:
    """Baseline browser cross-site request protection for unsafe requests.

    Browser POST/PUT/PATCH/DELETE requests with an Origin or Referer must point
    back to the same Host header. Requests without those browser headers remain
    allowed for internal tooling and tests. This is a baseline protection; a
    formal per-form CSRF token system can still be added in the hardening phase.
    """
    host = (host_header or '').strip().lower()
    if not host:
        return True
    candidate = origin_header or referer_header
    if not candidate:
        return True
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return False
    return parsed.netloc.strip().lower() == host
