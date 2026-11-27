"""Authentication and authorization dependencies for the CohortIQ AI API.

Stage 1 (this module) provides the request-level building blocks:

``get_current_user``
    Reads a ``Bearer`` token, validates it with :mod:`backend.app.core.security`
    and loads the account from the user store. Missing, malformed, expired,
    tampered or revoked tokens, unknown users and inactive users all receive
    the same generic HTTP 401 with ``WWW-Authenticate: Bearer``.

``require_role(*roles)``
    Builds a dependency that additionally requires one of the given roles,
    returning HTTP 403 otherwise. The role always comes from the user store,
    never from the token or the request. Refusals are recorded in the audit
    log as ``authorization.denied`` (see :class:`DenialRecorder`).

The user store is reached through ``get_user_store``, which is backed by the
``users`` table (:mod:`backend.app.auth.repository`) in the configured SQLite
database. If no store is available, or the lookup fails, authentication fails
closed with HTTP 503 for requests that present a valid token. There is no
fallback, placeholder or development user.

Which routes use these dependencies is recorded in
:mod:`backend.app.api.permissions`.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, Protocol

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.api.permissions import route_template_for
from backend.app.audit.repository import append_audit_event
from backend.app.auth.models import ROLE_ADMINISTRATOR, ROLE_STUDENT, ROLES, AuthenticatedUser
from backend.app.auth.repository import SQLiteUserStore
from backend.app.core.config import Settings, get_settings
from backend.app.core.security import AuthConfigurationError, AuthenticationError, decode_access_token

logger = logging.getLogger(__name__)

__all__ = [
    "AUTH_UNAVAILABLE_DETAIL",
    "FORBIDDEN_DETAIL",
    "NOT_AUTHENTICATED_DETAIL",
    "ROLES",
    "ROLE_ADMINISTRATOR",
    "ROLE_STUDENT",
    "AuthenticatedUser",
    "DenialRecorder",
    "UserStore",
    "get_auth_db_path",
    "get_auth_settings",
    "get_current_user",
    "get_denial_recorder",
    "get_user_store",
    "require_administrator",
    "require_role",
]

NOT_AUTHENTICATED_DETAIL = "Could not validate credentials."
FORBIDDEN_DETAIL = "Insufficient permissions."
AUTH_UNAVAILABLE_DETAIL = "Authentication is temporarily unavailable."

_bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")
_AUTH_SETTINGS = get_settings()


class UserStore(Protocol):
    """Interface a user store must implement."""

    def get_user_by_id(self, user_id: str) -> Optional[AuthenticatedUser]:
        """Return the account for ``user_id`` (the token subject), or None."""
        ...


def get_auth_db_path() -> Optional[str]:
    """Database path for the users table; ``None`` means the configured database.

    Tests override this to use an isolated temporary database.
    """
    return None


def get_user_store(db_path: Optional[str] = Depends(get_auth_db_path)) -> Optional[UserStore]:
    """Return the user store backed by the users table of the configured database."""
    return SQLiteUserStore(db_path)


def get_auth_settings() -> Settings:
    """Settings used to validate tokens (overridable in tests)."""
    return _AUTH_SETTINGS


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=NOT_AUTHENTICATED_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _unavailable() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=AUTH_UNAVAILABLE_DETAIL)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    settings: Settings = Depends(get_auth_settings),
    user_store: Optional[UserStore] = Depends(get_user_store),
) -> AuthenticatedUser:
    """Authenticate the request from its Bearer token. Never logs the token."""
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise _unauthorized()

    try:
        payload = decode_access_token(credentials.credentials, settings=settings)
    except AuthenticationError:
        raise _unauthorized() from None
    except AuthConfigurationError:
        logger.error("Authentication is not configured: signing secret missing or invalid.")
        raise _unavailable() from None

    if user_store is None:
        logger.error("Authentication is not available: no user store is configured.")
        raise _unavailable()

    try:
        user = user_store.get_user_by_id(payload.subject)
    except Exception:
        logger.exception("User lookup failed during authentication.")
        raise _unavailable() from None

    if user is None or not user.is_active:
        raise _unauthorized()
    if user.token_version != payload.token_version:
        # Token issued before a password change, deactivation or forced logout.
        raise _unauthorized()
    if user.role not in ROLES:
        logger.error("Account %s has an unrecognized role; access denied.", user.id)
        raise _unauthorized()
    return user


class DenialRecorder:
    """Records an authorization refusal (HTTP 403) in the audit log.

    The refusal is never weakened by auditing: if the event cannot be written,
    the failure is logged at ERROR level and the caller still refuses the
    request. Anonymous 401s are never recorded. The event stores the route
    template (not the concrete URL), the HTTP method and a reason code only.
    """

    def __init__(self, request: Request, db_path: Optional[str]) -> None:
        self._method = request.method
        self._path = route_template_for(request.method, request.url.path)
        self._db_path = db_path

    def __call__(self, user: AuthenticatedUser, reason: str) -> None:
        details: dict[str, str] = {"method": self._method, "reason": reason}
        if self._path is not None:
            details["path"] = self._path
        try:
            append_audit_event(
                "authorization.denied",
                outcome="denied",
                actor_type="user",
                actor_user_id=int(user.id),
                actor_role=user.role,
                details=details,
                db_path=self._db_path,
            )
        except Exception:
            logger.exception("Could not record an authorization refusal in the audit log.")


def get_denial_recorder(request: Request, db_path: Optional[str] = Depends(get_auth_db_path)) -> DenialRecorder:
    """Per-request recorder for authorization refusals (uses the users/audit database)."""
    return DenialRecorder(request, db_path)


def require_role(*allowed_roles: str) -> Callable[..., AuthenticatedUser]:
    """Return a dependency that requires the authenticated user to hold one of ``allowed_roles``.

    Raises ``ValueError`` at definition time for an empty or unknown role list,
    so a typo can never silently allow or deny everyone.
    """
    if not allowed_roles:
        raise ValueError("require_role needs at least one role.")
    unknown = [role for role in allowed_roles if role not in ROLES]
    if unknown:
        raise ValueError(f"Unknown role(s): {', '.join(unknown)}.")
    allowed = frozenset(allowed_roles)

    def dependency(
        user: AuthenticatedUser = Depends(get_current_user),
        record_denial: DenialRecorder = Depends(get_denial_recorder),
    ) -> AuthenticatedUser:
        if user.role not in allowed:
            record_denial(user, "insufficient_role")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FORBIDDEN_DETAIL)
        return user

    dependency.__name__ = "require_role_" + "_or_".join(sorted(allowed))
    return dependency


require_administrator = require_role(ROLE_ADMINISTRATOR)
"""Shared administrator-only dependency.

Routes use this single instance (rather than calling ``require_role`` again) so
the route inventory guard can verify administrator-only routes by identity.
"""
