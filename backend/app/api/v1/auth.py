"""Authentication API routes: sign-in and the current user's profile.

``POST /auth/login``
    Exchanges an email and password for an HS256 bearer token. Every refusal
    (unknown email, wrong password, inactive or temporarily locked account)
    returns the same HTTP 401 body, so callers cannot tell which applied.

``GET /auth/me``
    Returns the safe profile of the account identified by the bearer token,
    authenticated through :func:`backend.app.api.deps.get_current_user`.

``POST /auth/register``
    Public self-registration for students at the configured student email
    domain (default ``student.smvec.ac.in``). It can only
    create students, applies the existing password policy, requires a cohort,
    and records a ``user.created`` audit event (actor ``anonymous``) in the same
    transaction. It returns the profile, not a token: clients then sign in
    through ``/auth/login``. There is no email verification.

Administrators are still created only by the command-line bootstrap script.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status

from backend.app.api.deps import (
    AUTH_UNAVAILABLE_DETAIL,
    NOT_AUTHENTICATED_DETAIL,
    AuthenticatedUser,
    get_auth_db_path,
    get_auth_settings,
    get_current_user,
)
from backend.app.audit.repository import AuditEventError
from backend.app.auth.email_domains import email_matches_role_domain
from backend.app.auth.models import ROLE_STUDENT
from backend.app.auth.repository import DuplicateEmailError, WeakPasswordError, get_user_by_id, register_student
from backend.app.core.config import Settings
from backend.app.core.security import AuthConfigurationError
from backend.app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserProfileResponse
from backend.app.services import auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

LOGIN_FAILED_DETAIL = "Incorrect email or password."
ROLE_ACCESS_DENIED_DETAIL = "Access denied. This account does not match the selected role or permitted email domain."

_ERROR_SCHEMA = {
    "type": "object",
    "properties": {"detail": {"type": "string"}},
    "required": ["detail"],
}


def _error_response(description: str, example: str) -> dict:
    return {
        "description": description,
        "content": {"application/json": {"schema": _ERROR_SCHEMA, "example": {"detail": example}}},
    }


def _no_store(response: Response) -> None:
    """Credentials and profiles must not be cached by browsers or proxies."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _unavailable() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=AUTH_UNAVAILABLE_DETAIL)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Sign in with email and password",
    responses={
        401: _error_response(
            "The credentials were not accepted. The same response is returned for an unknown email, "
            "a wrong password, an inactive account and a temporarily locked account.",
            LOGIN_FAILED_DETAIL,
        ),
        403: _error_response("The credentials do not match the selected role or its permitted email domain.", ROLE_ACCESS_DENIED_DETAIL),
        422: {"description": "The request body is missing fields or is malformed."},
        503: _error_response("Authentication is temporarily unavailable.", AUTH_UNAVAILABLE_DETAIL),
    },
)
def login(
    credentials: LoginRequest,
    response: Response,
    settings: Settings = Depends(get_auth_settings),
    db_path: Optional[str | Path] = Depends(get_auth_db_path),
) -> TokenResponse:
    """Exchange credentials for a bearer token, optionally checking the selected role and its email domain."""
    try:
        issued = auth_service.login(credentials.email, credentials.password, settings=settings, db_path=db_path)
    except auth_service.LoginFailedError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=LOGIN_FAILED_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except AuthConfigurationError:
        logger.error("Sign-in is not available: signing secret missing or invalid.")
        raise _unavailable() from None
    except Exception:
        logger.exception("Sign-in failed because of an internal error.")
        raise _unavailable() from None

    if credentials.selected_role is not None and (
        credentials.selected_role != issued.role
        or not email_matches_role_domain(
            credentials.email,
            issued.role,
            settings,
            allow_legacy_student=True,
        )
    ):
        _no_store(response)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ROLE_ACCESS_DENIED_DETAIL,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    _no_store(response)
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Profile of the signed-in user",
    responses={
        401: _error_response(
            "Missing, invalid, expired or revoked token, or the account is inactive.",
            NOT_AUTHENTICATED_DETAIL,
        ),
        503: _error_response("Authentication is temporarily unavailable.", AUTH_UNAVAILABLE_DETAIL),
    },
)
def read_current_user_profile(
    response: Response,
    user: AuthenticatedUser = Depends(get_current_user),
    db_path: Optional[str | Path] = Depends(get_auth_db_path),
) -> UserProfileResponse:
    """Return the authenticated account's profile (never any security fields)."""
    try:
        record = get_user_by_id(user.id, db_path=db_path)
    except Exception:
        logger.exception("Profile lookup failed.")
        raise _unavailable() from None

    # Re-checked in case the account changed after the token was validated.
    if record is None or not record.is_active or record.token_version != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=NOT_AUTHENTICATED_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        )

    _no_store(response)
    return UserProfileResponse.model_validate(record)


DUPLICATE_ACCOUNT_DETAIL = "An account with this email already exists. Please sign in instead."
REGISTRATION_ERROR_DETAIL = "Registration is temporarily unavailable. Please try again later."


@router.post(
    "/register",
    response_model=UserProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a student account with a college email address",
    responses={
        409: _error_response("An account with this email already exists.", DUPLICATE_ACCOUNT_DETAIL),
        422: {"description": "Invalid email domain, weak password, missing cohort, or malformed body."},
        503: _error_response("Registration is temporarily unavailable.", REGISTRATION_ERROR_DETAIL),
    },
)
def register(
    request: RegisterRequest,
    response: Response,
    db_path: Optional[str | Path] = Depends(get_auth_db_path),
    settings: Settings = Depends(get_auth_settings),
) -> UserProfileResponse:
    """Create a student account; sign in afterwards with ``POST /auth/login``.

    Only the configured student email domain is accepted, the
    existing password policy applies, and the account is always a student with
    the admission batch and programme given here. No email verification is
    performed.
    """
    if not email_matches_role_domain(request.email, ROLE_STUDENT, settings):
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "type": "value_error",
                    "loc": ["body", "email"],
                    "msg": f"Use a student email address ending in @{settings.student_email_domain}.",
                }
            ],
        )
    try:
        record = register_student(
            request.email,
            request.password,
            admission_batch=request.admission_batch,
            programme=request.programme,
            full_name=request.full_name,
            db_path=db_path,
        )
    except DuplicateEmailError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE_ACCOUNT_DETAIL) from None
    except WeakPasswordError as error:
        # Policy messages describe the rule, never the password.
        raise HTTPException(
            status_code=422,
            detail=[{"type": "value_error", "loc": ["body", "password"],
                     "msg": "Password does not meet the password policy: " + " ".join(error.problems)}],
        ) from None
    except AuditEventError:
        logger.error("Registration failed: the audit event was rejected; no account was created.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=REGISTRATION_ERROR_DETAIL) from None
    except ValueError as error:
        # Remaining repository ValueErrors are input rules with fixed messages.
        raise HTTPException(
            status_code=422, detail=[{"type": "value_error", "loc": ["body"], "msg": str(error)}]
        ) from None
    except Exception:
        logger.exception("Registration failed because of an internal error; no account was created.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=REGISTRATION_ERROR_DETAIL) from None

    _no_store(response)
    return UserProfileResponse.model_validate(record)
