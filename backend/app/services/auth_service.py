"""Sign-in workflow for the CohortIQ AI API.

Reuses the existing primitives only: Argon2id verification and the dummy check
from :mod:`backend.app.core.security`, the HS256 token issuer
:func:`~backend.app.core.security.create_access_token`, and the users repository
for lookup and the atomic lockout bookkeeping.

Every refusal (unknown email, wrong password, inactive or locked account)
raises the same :class:`LoginFailedError`, and every path performs exactly one
Argon2id verification, so neither the result nor the timing reveals whether an
account exists or why sign-in was refused. Passwords and tokens are never logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from backend.app.auth.repository import apply_login_attempt, get_user_by_email
from backend.app.core.config import Settings
from backend.app.core.security import (
    create_access_token,
    ensure_token_signing_configured,
    perform_dummy_password_check,
    verify_password,
)


class LoginFailedError(Exception):
    """Sign-in was refused. Deliberately carries no reason."""

    def __init__(self) -> None:
        super().__init__("Sign-in refused.")


@dataclass(frozen=True)
class IssuedToken:
    """A newly issued access token. The token is hidden from ``repr``."""

    access_token: str = field(repr=False)
    expires_in: int


def login(
    email: str,
    password: str,
    *,
    settings: Settings,
    db_path: str | Path | None = None,
    now: Optional[datetime] = None,
) -> IssuedToken:
    """Verify credentials and issue an access token.

    Raises:
        LoginFailedError: the credentials were not accepted (any reason).
        AuthConfigurationError: tokens cannot be signed; raised before any
            account state is read or changed.
    """
    ensure_token_signing_configured(settings)

    user = get_user_by_email(email, db_path=db_path)
    if user is None:
        perform_dummy_password_check(password)
        raise LoginFailedError()

    # Verified even for inactive or locked accounts so timing stays uniform;
    # apply_login_attempt then decides with the account's current state.
    password_matches = verify_password(password, user.password_hash)
    signed_in = apply_login_attempt(
        user.id,
        verified_password_hash=user.password_hash,
        password_matches=password_matches,
        max_failed_attempts=settings.login_max_failed_attempts,
        lockout_duration=timedelta(minutes=settings.login_lockout_minutes),
        now=now,
        db_path=db_path,
    )
    if signed_in is None:
        raise LoginFailedError()

    token = create_access_token(signed_in.id, signed_in.token_version, settings=settings, now=now)
    return IssuedToken(access_token=token, expires_in=settings.access_token_expire_minutes * 60)
