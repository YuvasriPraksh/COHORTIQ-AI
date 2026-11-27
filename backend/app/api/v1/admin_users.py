"""Administrator user-management API routes (Part 4, Stage 5).

Every route requires an administrator (``require_administrator`` is attached to
the router, so a route added later cannot forget it) and maps to exactly one
atomic repository operation in :mod:`backend.app.auth.admin_repository`, which
re-checks the acting administrator inside its transaction and writes the audit
event in that same transaction.

Policy, enforced by the repository and only translated to HTTP here:

- Only students can be created; there is no role field on creation.
- The administrator role can never be granted. A promotion request reaches the
  repository, which refuses it and records the refusal (HTTP 403).
- Administrators cannot change their own role or active status, and cannot
  reset their own password or any administrator's password (HTTP 403).
- The last active administrator cannot be deactivated or demoted (HTTP 409).

Responses use the Task 3 schemas only: no password hash, token version, failed
sign-in counter or lock expiry is ever returned, and error details never echo
submitted values.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any, Callable, NoReturn, Optional, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query, Response, status

from backend.app.api.deps import FORBIDDEN_DETAIL, AuthenticatedUser, get_auth_db_path, require_administrator
from backend.app.api.permissions import ADMINISTRATOR_ONLY_RESPONSES
from backend.app.audit.repository import AuditEventError
from backend.app.auth import admin_repository
from backend.app.auth.admin_repository import (
    AdminActionRefusedError,
    ConcurrentModificationError,
    UserNotFoundError,
)
from backend.app.auth.repository import DuplicateEmailError, UserRecord, WeakPasswordError, get_user_by_id
from backend.app.schemas.admin import (
    MAX_ID,
    AdminUserListResponse,
    AdminUserResponse,
    PasswordResetRequest,
    RoleChangeRequest,
    StudentCreateRequest,
    UserListQuery,
    UserProfileUpdateRequest,
)

logger = logging.getLogger(__name__)

USER_NOT_FOUND_DETAIL = "User not found."
DUPLICATE_EMAIL_DETAIL = "An account with this email already exists."
RETRY_DETAIL = "The account changed during the operation; please retry."
USER_MANAGEMENT_ERROR_DETAIL = "The user-management request failed due to an internal server error."

# Policy refusals -> HTTP status. The messages come from fixed strings in the repository.
_REFUSAL_STATUS = {
    "self_change": status.HTTP_403_FORBIDDEN,
    "role_not_assignable": status.HTTP_403_FORBIDDEN,
    "administrator_account": status.HTTP_403_FORBIDDEN,
    "last_administrator": status.HTTP_409_CONFLICT,
}


def _no_store(response: Response) -> None:
    """Account data must not be cached by browsers or proxies."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(
    prefix="/admin/users",
    tags=["administration"],
    dependencies=[Depends(require_administrator), Depends(_no_store)],
    responses={
        **ADMINISTRATOR_ONLY_RESPONSES,
        500: {"description": "Internal server error. Details are logged, never returned."},
    },
)

UserId = Annotated[int, PathParam(ge=1, le=MAX_ID, description="Account id.")]
Administrator = Annotated[AuthenticatedUser, Depends(require_administrator)]
DbPath = Annotated[Optional[str | Path], Depends(get_auth_db_path)]

_NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {404: {"description": USER_NOT_FOUND_DETAIL}}
_REFUSAL_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"description": "Administrator role required, or the change is not permitted by policy."},
    409: {"description": "The last active administrator cannot be removed, or the account changed meanwhile."},
}

T = TypeVar("T")


def _validation_error(message: str, field: Optional[str] = None) -> HTTPException:
    """A 422 shaped like the API's request-validation errors (no input echoed)."""
    location = ["body", field] if field else ["body"]
    return HTTPException(status_code=422, detail=[{"type": "value_error", "loc": location, "msg": message}])


def _translate(error: Exception, operation: str) -> NoReturn:
    """Map repository outcomes to HTTP errors without leaking internal details."""
    if isinstance(error, AdminActionRefusedError):
        if error.reason == "actor_not_authorized":
            # The account lost administrator rights after authenticating.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FORBIDDEN_DETAIL) from None
        raise HTTPException(status_code=_REFUSAL_STATUS[error.reason], detail=str(error)) from None
    if isinstance(error, UserNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=USER_NOT_FOUND_DETAIL) from None
    if isinstance(error, DuplicateEmailError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE_EMAIL_DETAIL) from None
    if isinstance(error, ConcurrentModificationError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=RETRY_DETAIL) from None
    if isinstance(error, WeakPasswordError):
        # Policy messages describe the rule, never the password.
        raise _validation_error("Password does not meet the password policy: " + " ".join(error.problems)) from None
    if isinstance(error, AuditEventError):
        # Request schemas reject anything the audit log would refuse, so this is a server fault.
        logger.error("User management (%s) failed: the audit event was rejected.", operation)
        raise HTTPException(status_code=500, detail=USER_MANAGEMENT_ERROR_DETAIL) from None
    if isinstance(error, ValueError):
        # Remaining repository ValueErrors are input rules with fixed messages
        # (e.g. a student must keep a cohort); they never contain submitted values.
        raise _validation_error(str(error)) from None
    logger.exception("User management (%s) failed due to an unexpected error.", operation)
    raise HTTPException(status_code=500, detail=USER_MANAGEMENT_ERROR_DETAIL) from None


def _run(operation: str, call: Callable[[], T]) -> T:
    try:
        return call()
    except HTTPException:
        raise
    except Exception as error:  # translated, never passed through
        _translate(error, operation)


def _respond(record: UserRecord) -> AdminUserResponse:
    return AdminUserResponse.from_record(record)


# --------------------------------------------------------------------------- #
# Collection
# --------------------------------------------------------------------------- #


@router.get("", response_model=AdminUserListResponse, summary="List accounts")
def list_accounts(
    query: Annotated[UserListQuery, Query()],
    _administrator: Administrator,
    db_path: DbPath,
) -> AdminUserListResponse:
    """List accounts with optional role, status and cohort filters (bounded pagination)."""
    page = _run("list", lambda: admin_repository.list_users(**query.filters(), db_path=db_path))
    return AdminUserListResponse.from_page(page)


@router.post(
    "",
    response_model=AdminUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a student account",
    responses={409: {"description": DUPLICATE_EMAIL_DETAIL}},
)
def create_student_account(
    request: StudentCreateRequest,
    administrator: Administrator,
    db_path: DbPath,
) -> AdminUserResponse:
    """Create a student with a cohort and an administrator-set initial password.

    Administrators can only be created with the command-line bootstrap script.
    """
    record = _run(
        "create",
        lambda: admin_repository.create_student(
            administrator,
            email=request.email,
            password=request.password,
            admission_batch=request.admission_batch,
            programme=request.programme,
            full_name=request.full_name,
            db_path=db_path,
        ),
    )
    return _respond(record)


# --------------------------------------------------------------------------- #
# Single account
# --------------------------------------------------------------------------- #


@router.get("/{user_id}", response_model=AdminUserResponse, summary="Get an account", responses=_NOT_FOUND_RESPONSE)
def get_account(user_id: UserId, _administrator: Administrator, db_path: DbPath) -> AdminUserResponse:
    record = _run("get", lambda: get_user_by_id(user_id, db_path=db_path))
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=USER_NOT_FOUND_DETAIL)
    return _respond(record)


@router.patch(
    "/{user_id}",
    response_model=AdminUserResponse,
    summary="Update an account's name or cohort",
    responses=_NOT_FOUND_RESPONSE,
)
def update_account_profile(
    user_id: UserId,
    request: UserProfileUpdateRequest,
    administrator: Administrator,
    db_path: DbPath,
) -> AdminUserResponse:
    """Change the full name and/or cohort. Students must keep a cohort."""
    record = _run(
        "update_profile",
        lambda: admin_repository.update_profile(administrator, user_id, db_path=db_path, **request.changes()),
    )
    return _respond(record)


@router.patch(
    "/{user_id}/role",
    response_model=AdminUserResponse,
    summary="Change an account's role (demotion only)",
    responses={**_NOT_FOUND_RESPONSE, **_REFUSAL_RESPONSES},
)
def change_account_role(
    user_id: UserId,
    request: RoleChangeRequest,
    administrator: Administrator,
    db_path: DbPath,
) -> AdminUserResponse:
    """Demote an administrator to student; existing tokens are revoked.

    Granting the administrator role is always refused (and audited).
    """
    record = _run("change_role", lambda: admin_repository.change_role(administrator, user_id, request.role, db_path=db_path))
    return _respond(record)


@router.post(
    "/{user_id}/password",
    response_model=AdminUserResponse,
    summary="Reset a student's password",
    responses={**_NOT_FOUND_RESPONSE, **_REFUSAL_RESPONSES},
)
def reset_account_password(
    user_id: UserId,
    request: PasswordResetRequest,
    administrator: Administrator,
    db_path: DbPath,
) -> AdminUserResponse:
    """Set a student's password and revoke their tokens.

    Refused for the administrator's own account and for any administrator account.
    """
    record = _run(
        "reset_password",
        lambda: admin_repository.reset_password(administrator, user_id, request.new_password, db_path=db_path),
    )
    return _respond(record)


# --------------------------------------------------------------------------- #
# Bodyless account actions
# --------------------------------------------------------------------------- #


@router.post(
    "/{user_id}/deactivate",
    response_model=AdminUserResponse,
    summary="Deactivate an account",
    responses={**_NOT_FOUND_RESPONSE, **_REFUSAL_RESPONSES},
)
def deactivate_account(user_id: UserId, administrator: Administrator, db_path: DbPath) -> AdminUserResponse:
    """Deactivate the account and revoke its tokens.

    Refused for the administrator's own account and for the last active administrator.
    """
    return _respond(_run("deactivate", lambda: admin_repository.deactivate_account(administrator, user_id, db_path=db_path)))


@router.post(
    "/{user_id}/reactivate",
    response_model=AdminUserResponse,
    summary="Reactivate an account",
    responses=_NOT_FOUND_RESPONSE,
)
def reactivate_account(user_id: UserId, administrator: Administrator, db_path: DbPath) -> AdminUserResponse:
    """Reactivate an inactive account. Tokens revoked at deactivation stay revoked."""
    return _respond(_run("reactivate", lambda: admin_repository.reactivate_account(administrator, user_id, db_path=db_path)))


@router.post(
    "/{user_id}/unlock",
    response_model=AdminUserResponse,
    summary="Unlock an account",
    responses=_NOT_FOUND_RESPONSE,
)
def unlock_account(user_id: UserId, administrator: Administrator, db_path: DbPath) -> AdminUserResponse:
    """Clear the failed sign-in counter and any temporary sign-in lock."""
    return _respond(_run("unlock", lambda: admin_repository.unlock_account(administrator, user_id, db_path=db_path)))


@router.post(
    "/{user_id}/revoke-sessions",
    response_model=AdminUserResponse,
    summary="Revoke an account's sessions",
    responses=_NOT_FOUND_RESPONSE,
)
def revoke_sessions(user_id: UserId, administrator: Administrator, db_path: DbPath) -> AdminUserResponse:
    """Invalidate every access token issued to the account."""
    return _respond(_run("revoke_sessions", lambda: admin_repository.revoke_sessions(administrator, user_id, db_path=db_path)))
