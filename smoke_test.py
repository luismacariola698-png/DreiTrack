"""Non-destructive DreiTrack v0.4.1 installation and private-LAN smoke test."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import AppUser, Organization
from app.network import is_allowed_private_client, network_access_context, same_origin_or_local_request
from app.security import session_secret

client = TestClient(app)
REDIRECTS = {302, 303, 307, 308}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAILED: {message}")


anonymous = client.get("/", follow_redirects=False)
require(anonymous.status_code in REDIRECTS, f"anonymous / returned {anonymous.status_code}; expected redirect")
require(anonymous.headers.get("location") in {"/login", "/setup"}, "anonymous / did not redirect to /login or /setup")
print(f"OK {anonymous.status_code}: anonymous access is gated")

docs = client.get("/docs", follow_redirects=False)
require(docs.status_code in REDIRECTS, "anonymous API docs are exposed")
print("OK: anonymous API docs are gated")

with SessionLocal() as db:
    organization_count = db.scalar(select(func.count(Organization.id))) or 0
    user_count = db.scalar(select(func.count(AppUser.id))) or 0

require(organization_count <= 1, f"private-company build found {organization_count} organizations")
require(not (organization_count == 0 and user_count > 0), "users exist without a company")
require(not (organization_count == 1 and user_count == 0), "company exists without any user")

if organization_count == 0:
    setup = client.get("/setup")
    require(setup.status_code == 200, f"fresh-install /setup returned {setup.status_code}")
    print("OK: fresh installation setup page is available")
else:
    print("OK: exactly one company is configured")
    email = os.getenv("DREITRACK_SMOKE_EMAIL")
    password = os.getenv("DREITRACK_SMOKE_PASSWORD")
    if email and password:
        login = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
        require(login.status_code in {302, 303}, "smoke-test login was rejected")
        print("OK: authenticated smoke-test session created")
        for path in ("/", "/inventory", "/movements", "/orders", "/assets", "/requests", "/settings", "/insights", "/api/inventory"):
            response = client.get(path)
            require(response.status_code == 200, f"{path} returned {response.status_code}")
            print(f"OK {response.status_code}: {path}")
    else:
        print("SKIP: authenticated page checks require DREITRACK_SMOKE_EMAIL and DREITRACK_SMOKE_PASSWORD")

routes = {route.path for route in app.routes}
require(not ({"/register", "/robots", "/robots/create"} & routes), "forbidden/legacy routes remain")
required_routes = {
    "/setup", "/login", "/assets", "/assets/create", "/movements/transfer", "/settings",
    "/settings/sites/create", "/settings/locations/create", "/settings/asset-types/create",
    "/settings/users/create", "/settings/users/{user_id}/role", "/settings/users/{user_id}/active",
    "/insights/assistant", "/insights/attention", "/insights/overdue-orders",
}
missing = required_routes - routes
require(not missing, f"missing routes: {sorted(missing)}")
print("OK: required routes are registered")

network = network_access_context()
require(network["port"] >= 1, "invalid configured network port")
require(is_allowed_private_client("127.0.0.1"), "loopback client should be allowed")
require(is_allowed_private_client("192.168.1.50"), "private LAN client should be allowed")
require(not is_allowed_private_client("8.8.8.8"), "public numeric client should be rejected")
print("OK: private-network source IP rules")

require(
    same_origin_or_local_request(host_header="dreitrack-server:8000", origin_header="http://dreitrack-server:8000", referer_header=None),
    "valid same-origin request was rejected",
)
require(
    not same_origin_or_local_request(host_header="dreitrack-server:8000", origin_header="http://malicious.example", referer_header=None),
    "cross-site origin was accepted",
)
print("OK: baseline browser same-origin write protection")

secret_one = session_secret()
secret_two = session_secret()
require(bool(secret_one) and secret_one == secret_two and len(secret_one) >= 40, "installation session secret is not stable/strong")
print("OK: per-installation session secret")
print("DreiTrack v0.4.1 private-LAN smoke test passed.")
