"""Non-destructive DreiTrack v0.3 private-company smoke test."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import Organization


EMAIL = os.getenv("DREITRACK_SMOKE_EMAIL", "admin@demo.dreitrack")
PASSWORD = os.getenv("DREITRACK_SMOKE_PASSWORD", "ChangeMe123!")

client = TestClient(app)

anonymous = client.get("/", follow_redirects=False)
if anonymous.status_code not in {302, 303, 307, 308}:
    raise SystemExit(f"FAILED: anonymous / returned {anonymous.status_code}; expected redirect")
if anonymous.headers.get("location") not in {"/login", "/setup"}:
    raise SystemExit("FAILED: anonymous / did not redirect to /login or /setup")
print(f"OK {anonymous.status_code}: anonymous access is gated")

# API docs are not public in private-company mode.
docs = client.get("/docs", follow_redirects=False)
if docs.status_code not in {302, 303, 307, 308}:
    raise SystemExit("FAILED: anonymous API docs are exposed")
print("OK: anonymous API docs are gated")

login = client.post(
    "/login",
    data={"email": EMAIL, "password": PASSWORD},
    follow_redirects=False,
)
if login.status_code not in {302, 303}:
    raise SystemExit(
        "FAILED: smoke-test login was rejected. "
        "Set DREITRACK_SMOKE_EMAIL and DREITRACK_SMOKE_PASSWORD if credentials changed."
    )
print("OK: authenticated smoke-test session created")

EXPECTED_PAGES = (
    "/",
    "/inventory",
    "/movements",
    "/orders",
    "/assets",
    "/requests",
    "/settings",
    "/insights",
    "/api/inventory",
)

for path in EXPECTED_PAGES:
    response = client.get(path)
    if response.status_code != 200:
        raise SystemExit(f"FAILED: {path} returned {response.status_code}")
    print(f"OK {response.status_code}: {path}")

routes = {route.path for route in app.routes}

forbidden_routes = {
    "/register",
    "/robots",
    "/robots/create",
}
found_forbidden = forbidden_routes & routes
if found_forbidden:
    raise SystemExit(f"FAILED: forbidden/legacy routes remain: {sorted(found_forbidden)}")

required_routes = {
    "/setup",
    "/login",
    "/assets",
    "/assets/create",
    "/movements/transfer",
    "/settings",
    "/settings/sites/create",
    "/settings/locations/create",
    "/settings/asset-types/create",
    "/settings/users/create",
    "/settings/users/{user_id}/role",
    "/settings/users/{user_id}/active",
    "/insights/assistant",
    "/insights/attention",
    "/insights/overdue-orders",
}

missing = required_routes - routes
if missing:
    raise SystemExit(f"FAILED: missing routes: {sorted(missing)}")

with SessionLocal() as db:
    organization_count = db.scalar(select(func.count(Organization.id))) or 0
    if organization_count != 1:
        raise SystemExit(
            f"FAILED: private-company build expects exactly one organization; found {organization_count}"
        )
print("OK: exactly one company is configured")

print("DreiTrack v0.3 private-company smoke test passed.")
