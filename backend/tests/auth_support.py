"""Real sign-in support for API tests (Part 4, Stage 4).

Since Stage 4 the regulation and query endpoints require a bearer token. These
helpers create a genuine account in a temporary users database (random
password, no fixed credentials), sign in through the real login service, and
point the API's authentication dependencies at that temporary database and a
per-test signing secret.

Nothing here bypasses authentication: requests carry a real token that
``get_current_user`` validates against the temporary users table, exactly as
in production. There is no default account; each test module opts in
explicitly and chooses the role it needs.
"""

from __future__ import annotations

import functools
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.deps import get_auth_db_path, get_auth_settings
from backend.app.auth.models import ROLE_ADMINISTRATOR
from backend.app.auth.repository import UserRecord, create_user, init_auth_tables
from backend.app.core.config import Settings
from backend.app.services import auth_service


def random_password() -> str:
    return "Kp4#" + secrets.token_urlsafe(18)


def make_auth_settings(**overrides: object) -> Settings:
    """Test settings with a fresh random signing secret."""
    return Settings(app_env="test", jwt_secret_key=secrets.token_urlsafe(48), **overrides)


@dataclass(frozen=True)
class SignedInAccount:
    user: UserRecord
    password: str = field(repr=False)
    token: str = field(repr=False)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def create_signed_in_account(
    db_path: Path,
    settings: Settings,
    role: str,
    *,
    email: Optional[str] = None,
    admission_batch: Optional[str] = None,
    programme: Optional[str] = None,
    is_active: bool = True,
) -> SignedInAccount:
    """Create an account with a random password and sign in through the login service.

    Inactive accounts cannot sign in, so for them a token is issued while the
    account is still active and the account is then deactivated directly.
    """
    init_auth_tables(db_path)
    password = random_password()
    address = email or f"{role}-{secrets.token_hex(6)}@uni.edu"
    user = create_user(
        address, password, role, admission_batch=admission_batch, programme=programme, db_path=db_path
    )
    issued = auth_service.login(address, password, settings=settings, db_path=db_path)
    if not is_active:
        with closing(sqlite3.connect(db_path)) as connection:  # keep token_version unchanged
            connection.execute("UPDATE users SET is_active = 0 WHERE id = ?;", (user.id,))
            connection.commit()
    return SignedInAccount(user=user, password=password, token=issued.access_token)


def use_auth_database(app: FastAPI, monkeypatch: pytest.MonkeyPatch, db_path: Path, settings: Settings) -> None:
    """Point the app's authentication at ``db_path`` and ``settings`` for one test."""
    monkeypatch.setitem(app.dependency_overrides, get_auth_db_path, lambda: str(db_path))
    monkeypatch.setitem(app.dependency_overrides, get_auth_settings, lambda: settings)


def sign_in_module_clients_as_administrator(
    module: ModuleType, app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> SignedInAccount:
    """Make every ``TestClient`` the test module creates send an administrator's token.

    For test modules that exercise administrator workflows (ingestion,
    verification, viewing unapproved regulations, querying any cohort) and were
    written before endpoints were protected. A real administrator account is
    created in a temporary users database for each test and signed in through
    the login service; its token is added to the clients' default headers.
    Authorization rules themselves are tested in ``test_authorization.py``.
    """
    settings = make_auth_settings()
    db_path = tmp_path / "auth" / "users.db"
    account = create_signed_in_account(db_path, settings, ROLE_ADMINISTRATOR)
    use_auth_database(app, monkeypatch, db_path, settings)
    monkeypatch.setattr(module, "TestClient", functools.partial(TestClient, headers=account.headers))
    return account
