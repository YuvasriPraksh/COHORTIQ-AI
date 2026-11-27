"""API permission inventory and authorization rules (Part 4, Stage 4).

``ROUTE_PERMISSIONS`` classifies every registered route, including the
documentation routes FastAPI adds:

``PUBLIC``
    No token required.
``AUTHENTICATED``
    Any active student or administrator (``get_current_user``). Some of these
    routes narrow results further by role, as described in their handlers.
``ADMINISTRATOR``
    Administrators only (``require_administrator``); students receive 403.

A guard test (``backend/tests/test_route_permissions.py``) fails when a route
exists without a classification, when a classification names a route that no
longer exists, or when a route's dependencies do not match its classification.

Authorization always uses the role and cohort stored in the users table (as
loaded by ``get_current_user``), never values from the token or the request.
"""

from __future__ import annotations

import re
from enum import Enum
from types import MappingProxyType
from typing import Callable, Mapping, Optional

from fastapi import HTTPException, status

from backend.app.auth.models import ROLE_ADMINISTRATOR, ROLE_STUDENT, AuthenticatedUser
from backend.app.core.config import get_settings

COHORT_FORBIDDEN_DETAIL = "You can only access regulations for your own cohort."

# OpenAPI documentation for the authorization outcomes of protected routes.
UNAUTHENTICATED_RESPONSE: dict[int | str, dict] = {
    401: {"description": "Missing, invalid, expired or revoked bearer token, or inactive account."}
}
ADMINISTRATOR_ONLY_RESPONSES: dict[int | str, dict] = {
    **UNAUTHENTICATED_RESPONSE,
    403: {"description": "Administrator role required."},
}
COHORT_SCOPED_RESPONSES: dict[int | str, dict] = {
    **UNAUTHENTICATED_RESPONSE,
    403: {"description": "Students may only use the admission batch and programme of their own account."},
}


class Access(str, Enum):
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    ADMINISTRATOR = "administrator"


_API = get_settings().api_v1_prefix

ROUTE_PERMISSIONS: Mapping[tuple[str, str], Access] = MappingProxyType(
    {
        # Service and documentation
        ("GET", "/"): Access.PUBLIC,
        ("GET", "/openapi.json"): Access.PUBLIC,
        ("GET", "/docs"): Access.PUBLIC,
        ("GET", "/docs/oauth2-redirect"): Access.PUBLIC,
        ("GET", "/redoc"): Access.PUBLIC,
        ("GET", f"{_API}/health"): Access.PUBLIC,
        # Authentication
        ("POST", f"{_API}/auth/login"): Access.PUBLIC,
        ("GET", f"{_API}/auth/me"): Access.AUTHENTICATED,
        # Regulation reads: students see approved regulations only
        ("GET", f"{_API}/regulations"): Access.AUTHENTICATED,
        ("GET", f"{_API}/regulations/{{regulation_id}}"): Access.AUTHENTICATED,
        ("GET", f"{_API}/regulations/{{regulation_id}}/pages"): Access.AUTHENTICATED,
        # Cohort-scoped: students are limited to their own cohort
        ("GET", f"{_API}/cohorts/{{admission_batch}}/{{programme}}/regulations"): Access.AUTHENTICATED,
        ("POST", f"{_API}/query/ask"): Access.AUTHENTICATED,
        # Regulation management
        ("POST", f"{_API}/regulations/ingest"): Access.ADMINISTRATOR,
        ("PATCH", f"{_API}/regulations/{{regulation_id}}/verification"): Access.ADMINISTRATOR,
        # Administrator user management (students only; administrators are CLI-created)
        ("GET", f"{_API}/admin/users"): Access.ADMINISTRATOR,
        ("POST", f"{_API}/admin/users"): Access.ADMINISTRATOR,
        ("GET", f"{_API}/admin/users/{{user_id}}"): Access.ADMINISTRATOR,
        ("PATCH", f"{_API}/admin/users/{{user_id}}"): Access.ADMINISTRATOR,
        ("PATCH", f"{_API}/admin/users/{{user_id}}/role"): Access.ADMINISTRATOR,
        ("POST", f"{_API}/admin/users/{{user_id}}/password"): Access.ADMINISTRATOR,
        ("POST", f"{_API}/admin/users/{{user_id}}/deactivate"): Access.ADMINISTRATOR,
        ("POST", f"{_API}/admin/users/{{user_id}}/reactivate"): Access.ADMINISTRATOR,
        ("POST", f"{_API}/admin/users/{{user_id}}/unlock"): Access.ADMINISTRATOR,
        ("POST", f"{_API}/admin/users/{{user_id}}/revoke-sessions"): Access.ADMINISTRATOR,
        # Audit log (read-only)
        ("GET", f"{_API}/admin/audit-events"): Access.ADMINISTRATOR,
    }
)


def _template_pattern(template: str) -> re.Pattern[str]:
    parts = [r"[^/]+" if re.fullmatch(r"\{[^/{}]+\}", part) else re.escape(part) for part in template.split("/")]
    return re.compile("^" + "/".join(parts) + "/?$")


# Literal routes first, so "/regulations/ingest" wins over "/regulations/{regulation_id}".
_TEMPLATE_PATTERNS = sorted(
    ((method, template, _template_pattern(template)) for method, template in ROUTE_PERMISSIONS),
    key=lambda entry: entry[1].count("{"),
)


def route_template_for(method: str, path: str) -> Optional[str]:
    """Return the classified route template matching a request, e.g. ``/api/v1/regulations/{regulation_id}``.

    Used to record *which route* was refused without storing concrete URLs,
    which may contain user data such as cohort names.
    """
    for candidate_method, template, pattern in _TEMPLATE_PATTERNS:
        if candidate_method == method.upper() and pattern.match(path):
            return template
    return None


def is_administrator(user: AuthenticatedUser) -> bool:
    return user.role == ROLE_ADMINISTRATOR


def ensure_cohort_access(
    user: AuthenticatedUser,
    admission_batch: str,
    programme: str,
    *,
    record_denial: Optional[Callable[[AuthenticatedUser, str], None]] = None,
) -> tuple[str, str]:
    """Return the cohort the user may act on, or raise HTTP 403.

    Administrators may use any cohort. A student may only use the admission
    batch and programme stored on their account; the values must match exactly
    (as regulation applicability matching does), and the stored values are
    returned so the caller never proceeds with request-supplied ones. Students
    without a stored cohort, and any unrecognized role, are refused.

    ``record_denial(user, reason)`` is called before a refusal is raised so it
    can be audited (see ``backend.app.api.deps.get_denial_recorder``).
    """
    if is_administrator(user):
        return admission_batch, programme
    if (
        user.role == ROLE_STUDENT
        and user.admission_batch
        and user.programme
        and admission_batch == user.admission_batch
        and programme == user.programme
    ):
        return user.admission_batch, user.programme
    if record_denial is not None:
        record_denial(user, "cohort_mismatch")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=COHORT_FORBIDDEN_DETAIL)
