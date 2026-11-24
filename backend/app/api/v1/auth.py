"""Authentication API routes: sign-in and the current user's profile.

``POST /auth/login``
    Exchanges an email and password for an HS256 bearer token. Every refusal
    (unknown email, wrong password, inactive or temporarily locked account)
    returns the same HTTP 401 body, so callers cannot tell which applied.

``GET /auth/me``
    Returns the safe profile of the account identified by the bearer token,
    authenticated through :func:`backend.app.api.deps.get_current_user`.

There is deliberately no registration or user-management route.
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
from backend.app.auth.repository import get_user_by_id
from backend.app.core.config import Settings
from backend.app.core.security import AuthConfigurationError
from backend.app.schemas.auth import LoginRequest, TokenResponse, UserProfileResponse
from backend.app.services import auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

LOGIN_FAILED_DETAIL = "Incorrect email or password."

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
    """Exchange an email and password for a bearer access token."""
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
