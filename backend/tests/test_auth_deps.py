"""Authentication dependencies (Part 4.2, Stage 1).

The dependencies are exercised on a small dedicated FastAPI app, because no
existing route is protected yet. The user store is a test double (an in-memory
dictionary); production code has no fallback or placeholder users.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.database import init_database
from backend.app.api import deps
from backend.app.api.deps import (
    AUTH_UNAVAILABLE_DETAIL,
    FORBIDDEN_DETAIL,
    NOT_AUTHENTICATED_DETAIL,
    AuthenticatedUser,
    get_auth_settings,
    get_current_user,
    get_user_store,
    require_role,
)
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.core.config import DEFAULT_JWT_AUDIENCE, DEFAULT_JWT_ISSUER, Settings
from backend.app.core.security import create_access_token
from backend.app.main import app as main_app

STUDENT = AuthenticatedUser(id="1", role="student", is_active=True, token_version=0, admission_batch="2024", programme="BSc CS")
ADMIN = AuthenticatedUser(id="2", role="administrator", is_active=True, token_version=0)
INACTIVE = AuthenticatedUser(id="3", role="administrator", is_active=False, token_version=0)
ROTATED = AuthenticatedUser(id="4", role="student", is_active=True, token_version=2)
UNKNOWN_ROLE = AuthenticatedUser(id="5", role="superuser", is_active=True, token_version=0)


class InMemoryUserStore:
    """Test double implementing the UserStore interface."""

    def __init__(self, *users: AuthenticatedUser) -> None:
        self.users = {user.id: user for user in users}
        self.lookups: list[str] = []

    def get_user_by_id(self, user_id: str) -> Optional[AuthenticatedUser]:
        self.lookups.append(user_id)
        return self.users.get(user_id)


class Env:
    def __init__(self, client: TestClient, settings: Settings, store: InMemoryUserStore) -> None:
        self.client = client
        self.settings = settings
        self.store = store

    def token_for(self, user_id: str, version: int = 0, **kwargs: Any) -> str:
        return create_access_token(user_id, version, settings=self.settings, **kwargs)

    def get(self, path: str, token: Optional[str] = None, scheme: str = "Bearer"):
        headers = {"Authorization": f"{scheme} {token}"} if token is not None else {}
        return self.client.get(path, headers=headers)


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/me")
    def me(user: AuthenticatedUser = Depends(get_current_user)) -> dict[str, Any]:
        return {"id": user.id, "role": user.role}

    @app.get("/admin-only")
    def admin_only(user: AuthenticatedUser = Depends(require_role("administrator"))) -> dict[str, Any]:
        return {"id": user.id}

    @app.get("/students-and-admins")
    def shared(user: AuthenticatedUser = Depends(require_role("student", "administrator"))) -> dict[str, Any]:
        return {"id": user.id}

    @app.get("/student-only")
    def student_only(user: AuthenticatedUser = Depends(require_role("student"))) -> dict[str, Any]:
        return {"id": user.id}

    return app


@pytest.fixture
def env() -> Iterator[Env]:
    settings = Settings(app_env="test", jwt_secret_key=secrets.token_urlsafe(48))
    store = InMemoryUserStore(STUDENT, ADMIN, INACTIVE, ROTATED, UNKNOWN_ROLE)
    app = _build_app()
    app.dependency_overrides[get_auth_settings] = lambda: settings
    app.dependency_overrides[get_user_store] = lambda: store
    yield Env(TestClient(app), settings, store)


def _assert_401(response: Any) -> None:
    assert response.status_code == 401
    assert response.json() == {"detail": NOT_AUTHENTICATED_DETAIL}
    assert response.headers.get("www-authenticate") == "Bearer"


# --------------------------------------------------------------------------- #
# get_current_user
# --------------------------------------------------------------------------- #


def test_valid_token_authenticates_user_from_store(env: Env) -> None:
    response = env.get("/me", env.token_for("1"))

    assert response.status_code == 200
    assert response.json() == {"id": "1", "role": "student"}
    assert env.store.lookups == ["1"]


def test_missing_authorization_header_returns_401(env: Env) -> None:
    _assert_401(env.get("/me"))
    assert env.store.lookups == []


@pytest.mark.parametrize("scheme", ["Basic", "Token", "JWT"])
def test_non_bearer_schemes_return_401(env: Env, scheme: str) -> None:
    _assert_401(env.get("/me", env.token_for("1"), scheme=scheme))


def test_lowercase_bearer_scheme_is_accepted(env: Env) -> None:
    assert env.get("/me", env.token_for("1"), scheme="bearer").status_code == 200


@pytest.mark.parametrize("token", ["", "garbage", "a.b.c", "x" * 5000])
def test_malformed_tokens_return_401(env: Env, token: str) -> None:
    _assert_401(env.get("/me", token))
    assert env.store.lookups == []


def test_expired_token_returns_401(env: Env) -> None:
    issued = datetime.now(timezone.utc) - timedelta(hours=2)
    _assert_401(env.get("/me", env.token_for("1", now=issued)))


def test_tampered_token_returns_401(env: Env) -> None:
    header, payload, signature = env.token_for("1").split(".")
    _assert_401(env.get("/me", ".".join([header, payload, signature[::-1]])))


def test_token_signed_with_another_secret_returns_401(env: Env) -> None:
    other = Settings(app_env="test", jwt_secret_key=secrets.token_urlsafe(48))
    _assert_401(env.get("/me", create_access_token("2", 0, settings=other)))


def test_unknown_user_returns_401(env: Env) -> None:
    _assert_401(env.get("/me", env.token_for("999")))


def test_inactive_user_returns_401(env: Env) -> None:
    _assert_401(env.get("/me", env.token_for("3")))


def test_revoked_token_version_returns_401(env: Env) -> None:
    _assert_401(env.get("/me", env.token_for("4", version=0)))
    _assert_401(env.get("/me", env.token_for("4", version=1)))
    assert env.get("/me", env.token_for("4", version=2)).status_code == 200


def test_unrecognized_stored_role_is_denied(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="backend.app.api.deps"):
        _assert_401(env.get("/me", env.token_for("5")))
    assert "unrecognized role" in caplog.text


def test_all_authentication_failures_are_indistinguishable(env: Env) -> None:
    issued = datetime.now(timezone.utc) - timedelta(hours=2)
    failures = [
        env.get("/me"),
        env.get("/me", "garbage"),
        env.get("/me", env.token_for("1", now=issued)),
        env.get("/me", env.token_for("999")),
        env.get("/me", env.token_for("3")),
        env.get("/me", env.token_for("4", version=0)),
    ]
    assert {(r.status_code, r.text, r.headers.get("www-authenticate")) for r in failures} == {
        (401, '{"detail":"Could not validate credentials."}', "Bearer")
    }


# --------------------------------------------------------------------------- #
# Roles are never taken from the token
# --------------------------------------------------------------------------- #


def _forged_role_token(env: Env, user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": user_id,
        "ver": 0,
        "jti": secrets.token_hex(16),
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=10),
        "iss": DEFAULT_JWT_ISSUER,
        "aud": DEFAULT_JWT_AUDIENCE,
        "role": role,
        "roles": [role],
        "is_admin": True,
    }
    return jwt.encode(claims, env.settings.jwt_secret_key, algorithm="HS256")


def test_role_claim_in_token_cannot_escalate_a_student(env: Env) -> None:
    token = _forged_role_token(env, "1", "administrator")

    assert env.get("/me", token).json() == {"id": "1", "role": "student"}
    response = env.get("/admin-only", token)
    assert response.status_code == 403
    assert response.json() == {"detail": FORBIDDEN_DETAIL}


def test_role_claim_in_token_cannot_demote_an_administrator(env: Env) -> None:
    token = _forged_role_token(env, "2", "student")

    assert env.get("/me", token).json() == {"id": "2", "role": "administrator"}
    assert env.get("/admin-only", token).status_code == 200


def test_role_in_query_string_or_headers_is_ignored(env: Env) -> None:
    response = env.client.get(
        "/admin-only?role=administrator",
        headers={"Authorization": f"Bearer {env.token_for('1')}", "X-Role": "administrator"},
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# require_role
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("path", "user_id", "expected"),
    [
        ("/admin-only", "2", 200),
        ("/admin-only", "1", 403),
        ("/students-and-admins", "1", 200),
        ("/students-and-admins", "2", 200),
        ("/student-only", "1", 200),
        ("/student-only", "2", 403),
    ],
)
def test_role_permission_matrix(env: Env, path: str, user_id: str, expected: int) -> None:
    response = env.get(path, env.token_for(user_id))

    assert response.status_code == expected
    if expected == 403:
        assert response.json() == {"detail": FORBIDDEN_DETAIL}


@pytest.mark.parametrize("path", ["/admin-only", "/students-and-admins", "/student-only"])
def test_unauthenticated_requests_get_401_not_403(env: Env, path: str) -> None:
    _assert_401(env.get(path))


@pytest.mark.parametrize("roles", [(), ("superuser",), ("student", "Administrator"), ("admin",)])
def test_require_role_rejects_empty_or_unknown_roles(roles: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        require_role(*roles)


# --------------------------------------------------------------------------- #
# Fail-closed behaviour and secrecy
# --------------------------------------------------------------------------- #


def test_no_user_store_fails_closed_with_503(env: Env) -> None:
    app = _build_app()
    app.dependency_overrides[get_auth_settings] = lambda: env.settings
    app.dependency_overrides[get_user_store] = lambda: None  # store unavailable
    client = TestClient(app)

    response = client.get("/me", headers={"Authorization": f"Bearer {env.token_for('2')}"})

    assert response.status_code == 503
    assert response.json() == {"detail": AUTH_UNAVAILABLE_DETAIL}
    _assert_401(client.get("/me"))  # anonymous requests are still plain 401


def test_default_user_store_is_the_users_database(tmp_path: Path) -> None:
    """Stage 2: the default store reads the users table; it holds no built-in users."""
    from backend.app.auth.repository import SQLiteUserStore, init_auth_tables

    db_path = tmp_path / "empty_users.db"
    init_auth_tables(db_path)

    store = get_user_store(db_path=str(db_path))

    assert isinstance(store, SQLiteUserStore)
    assert store.get_user_by_id("1") is None


def test_missing_signing_secret_fails_closed_with_503(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    token = env.token_for("2")
    app = _build_app()
    app.dependency_overrides[get_auth_settings] = lambda: Settings(app_env="development")
    app.dependency_overrides[get_user_store] = lambda: env.store
    client = TestClient(app)

    with caplog.at_level(logging.ERROR, logger="backend.app.api.deps"):
        response = client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 503
    assert response.json() == {"detail": AUTH_UNAVAILABLE_DETAIL}
    assert token not in caplog.text


def test_user_store_failure_returns_503_without_details(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    class BrokenStore:
        def get_user_by_id(self, user_id: str) -> Optional[AuthenticatedUser]:
            raise RuntimeError(f"database at C:\\private\\users.db unavailable for {user_id}")

    app = _build_app()
    app.dependency_overrides[get_auth_settings] = lambda: env.settings
    app.dependency_overrides[get_user_store] = lambda: BrokenStore()
    token = env.token_for("2")

    with caplog.at_level(logging.ERROR, logger="backend.app.api.deps"):
        response = TestClient(app).get("/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 503
    assert response.json() == {"detail": AUTH_UNAVAILABLE_DETAIL}
    assert "private" not in response.text
    assert "User lookup failed" in caplog.text
    assert token not in caplog.text


def test_tokens_and_secrets_never_appear_in_responses_or_logs(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    valid = env.token_for("1")
    attempts = [valid, valid[:-3] + "abc", env.token_for("999"), env.token_for("5"), _forged_role_token(env, "1", "administrator")]

    with caplog.at_level(logging.DEBUG):
        responses = [env.get(path, token) for token in attempts for path in ("/me", "/admin-only")]

    for response in responses:
        for token in attempts:
            assert token not in response.text
        assert env.settings.jwt_secret_key not in response.text
    for token in attempts:
        assert token not in caplog.text
    assert env.settings.jwt_secret_key not in caplog.text


def test_authenticated_user_carries_no_credentials() -> None:
    field_names = set(AuthenticatedUser.__dataclass_fields__)
    assert not any(word in name for name in field_names for word in ("password", "hash", "token_value", "secret"))


# --------------------------------------------------------------------------- #
# Scope guard: existing routes are not protected yet (Stage 4)
# --------------------------------------------------------------------------- #


def test_existing_routes_remain_unprotected_in_stage_1(tmp_path: Path) -> None:
    db_path = tmp_path / "scope.db"
    init_database(db_path)
    main_app.dependency_overrides[regulation_routes.get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(main_app)
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/regulations").status_code == 200
    finally:
        main_app.dependency_overrides.pop(regulation_routes.get_db_path, None)

    schema = TestClient(main_app).get("/openapi.json").json()
    assert "securitySchemes" not in schema.get("components", {})
    assert deps.get_current_user not in [
        dependency.call for route in main_app.routes for dependency in getattr(getattr(route, "dependant", None), "dependencies", [])
    ]
