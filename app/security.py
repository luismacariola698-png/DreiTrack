from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from collections.abc import Callable

from fastapi import HTTPException, Request


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000

ROLE_ADMIN = "ADMIN"
ROLE_MANAGER = "MANAGER"
ROLE_STAFF = "STAFF"
ROLE_VIEWER = "VIEWER"

VALID_ROLES = {
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_STAFF,
    ROLE_VIEWER,
}

WRITE_ROLES = {
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_STAFF,
}

MANAGEMENT_ROLES = {
    ROLE_ADMIN,
    ROLE_MANAGER,
}


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")

    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )

    return "$".join(
        (
            PASSWORD_SCHEME,
            str(PASSWORD_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(derived).decode("ascii"),
        )
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iterations_text, salt_text, hash_text = stored_hash.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False

        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(hash_text.encode("ascii"))
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def session_secret() -> str:
    """Return the session signing secret.

    Set DREITRACK_SESSION_SECRET in production. The fallback is intentionally
    development-only so a freshly extracted local project still starts.
    """

    return os.getenv(
        "DREITRACK_SESSION_SECRET",
        "dreitrack-local-development-secret-change-before-deployment",
    )


def current_user(request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def require_roles(*allowed_roles: str) -> Callable:
    allowed = {role.upper() for role in allowed_roles}

    def dependency(request: Request):
        user = current_user(request)
        if user.role not in allowed:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to perform this action.",
            )
        return user

    return dependency
