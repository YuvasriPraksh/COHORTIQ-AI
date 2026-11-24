"""Password hashing and JWT access-token primitives for CohortIQ AI.

Passwords
    Hashed with Argon2id (``argon2-cffi`` defaults: RFC 9106 low-memory profile).
    Plaintext passwords are never stored, logged or returned.

Access tokens
    JWTs signed with HS256 only. The algorithm is fixed in code and is never
    read from configuration or from the token header, which rules out
    ``alg=none`` and algorithm-confusion attacks. Every token carries ``sub``,
    ``iat``, ``nbf``, ``exp``, ``iss``, ``aud``, ``jti`` and ``ver`` (the user's
    token version, used for revocation). Decoding requires all of them and
    verifies the signature, expiry, not-before, issued-at, issuer and audience.

    Tokens deliberately carry **no role**: authorization must always use the
    role stored server-side for the user. Any ``role`` claim present in a token
    is ignored and never exposed by :func:`decode_access_token`.

Errors
    Validation failures raise :class:`AuthenticationError` with one generic
    message, so callers cannot leak which check failed. Missing signing
    configuration raises :class:`AuthConfigurationError`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from backend.app.core.config import Settings, get_settings, jwt_secret_weakness

JWT_ALGORITHM = "HS256"
"""The only accepted signing algorithm. Not configurable on purpose."""

REQUIRED_TOKEN_CLAIMS = ("sub", "iat", "nbf", "exp", "iss", "aud", "jti", "ver")

MAX_PASSWORD_LENGTH = 1024
"""Upper bound on password length to avoid hashing arbitrarily large inputs."""

MAX_TOKEN_LENGTH = 4096
"""Tokens longer than this are rejected before any parsing."""

GENERIC_AUTHENTICATION_ERROR = "Invalid or expired token."

_password_hasher = PasswordHasher(type=Type.ID)
_dummy_password_hash: str | None = None


class AuthenticationError(Exception):
    """A token could not be validated. The message is always generic."""

    def __init__(self) -> None:
        super().__init__(GENERIC_AUTHENTICATION_ERROR)


class AuthConfigurationError(RuntimeError):
    """Authentication cannot run because signing configuration is missing or invalid."""


@dataclass(frozen=True)
class TokenPayload:
    """Validated access-token claims. Intentionally has no role attribute."""

    subject: str
    token_version: int
    jwt_id: str
    issued_at: datetime
    expires_at: datetime


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #


def _validate_password_input(password: Any) -> str:
    if not isinstance(password, str):
        raise ValueError("Password must be a string.")
    if not password:
        raise ValueError("Password must not be empty.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters.")
    return password


def hash_password(password: str) -> str:
    """Return an Argon2id hash (with a random salt) for ``password``."""
    return _password_hasher.hash(_validate_password_input(password))


def verify_password(password: str, password_hash: str) -> bool:
    """Return True only if ``password`` matches ``password_hash``.

    Never raises for bad input: wrong passwords, malformed or non-Argon2 hashes
    and non-string values all return False.
    """
    if not isinstance(password, str) or not isinstance(password_hash, str):
        return False
    if not password or len(password) > MAX_PASSWORD_LENGTH or not password_hash:
        return False
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """Return True if ``password_hash`` uses weaker parameters than the current policy."""
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


def perform_dummy_password_check(password: Any) -> bool:
    """Spend the same effort as a real verification and always return False.

    Used when a login names an unknown account, so response timing does not
    reveal whether the account exists. The dummy hash is of a random value
    generated at runtime; it is not a usable credential.
    """
    global _dummy_password_hash
    if _dummy_password_hash is None:
        _dummy_password_hash = _password_hasher.hash(uuid.uuid4().hex)
    candidate = password if isinstance(password, str) and password else "-"
    verify_password(candidate[:MAX_PASSWORD_LENGTH], _dummy_password_hash)
    return False


# --------------------------------------------------------------------------- #
# Access tokens
# --------------------------------------------------------------------------- #


def _signing_secret(settings: Settings) -> str:
    secret = settings.jwt_secret_key
    if not secret:
        raise AuthConfigurationError("JWT_SECRET_KEY is not configured.")
    if jwt_secret_weakness(secret) is not None:
        raise AuthConfigurationError("JWT_SECRET_KEY does not meet the minimum strength requirements.")
    return secret


def ensure_token_signing_configured(settings: Settings | None = None) -> None:
    """Raise :class:`AuthConfigurationError` unless tokens can be signed.

    Lets callers fail before doing any work (such as updating sign-in state)
    when the signing secret is missing or weak.
    """
    _signing_secret(settings or get_settings())


def _validate_subject(subject: Any) -> str:
    if isinstance(subject, bool) or not isinstance(subject, (str, int)):
        raise ValueError("Token subject must be a non-empty string or integer.")
    value = str(subject).strip()
    if not value:
        raise ValueError("Token subject must be a non-empty string or integer.")
    return value


def _validate_token_version(token_version: Any) -> int:
    if isinstance(token_version, bool) or not isinstance(token_version, int) or token_version < 0:
        raise ValueError("Token version must be a non-negative integer.")
    return token_version


def create_access_token(
    subject: str | int,
    token_version: int,
    *,
    settings: Settings | None = None,
    expires_delta: timedelta | None = None,
    now: datetime | None = None,
) -> str:
    """Create a signed HS256 access token for a user.

    There is intentionally no ``role`` parameter: roles are never placed in
    tokens and must be looked up server-side on every request.
    """
    resolved = settings or get_settings()
    secret = _signing_secret(resolved)
    subject_value = _validate_subject(subject)
    version = _validate_token_version(token_version)

    lifetime = expires_delta if expires_delta is not None else timedelta(minutes=resolved.access_token_expire_minutes)
    if lifetime <= timedelta(0):
        raise ValueError("Token lifetime must be positive.")

    issued_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    claims = {
        "sub": subject_value,
        "ver": version,
        "jti": uuid.uuid4().hex,
        "iat": issued_at,
        "nbf": issued_at,
        "exp": issued_at + lifetime,
        "iss": resolved.jwt_issuer,
        "aud": resolved.jwt_audience,
    }
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, *, settings: Settings | None = None) -> TokenPayload:
    """Validate an access token and return its claims.

    Raises:
        AuthenticationError: for any invalid, expired, tampered, incorrectly
            signed or incomplete token (always the same generic message).
        AuthConfigurationError: if the signing secret is not configured.
    """
    resolved = settings or get_settings()
    secret = _signing_secret(resolved)

    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_LENGTH:
        raise AuthenticationError()

    try:
        header = jwt.get_unverified_header(token)
        # Defence in depth: PyJWT already enforces ``algorithms`` below.
        if header.get("alg") != JWT_ALGORITHM:
            raise AuthenticationError()
        claims = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            audience=resolved.jwt_audience,
            issuer=resolved.jwt_issuer,
            leeway=resolved.jwt_leeway_seconds,
            options={
                "require": list(REQUIRED_TOKEN_CLAIMS),
                "verify_signature": True,
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except AuthenticationError:
        raise
    except (jwt.PyJWTError, ValueError, TypeError):
        raise AuthenticationError() from None

    return _payload_from_claims(claims)


def _payload_from_claims(claims: dict[str, Any]) -> TokenPayload:
    subject = claims.get("sub")
    version = claims.get("ver")
    jwt_id = claims.get("jti")
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")

    if not isinstance(subject, str) or not subject.strip():
        raise AuthenticationError()
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise AuthenticationError()
    if not isinstance(jwt_id, str) or not jwt_id.strip():
        raise AuthenticationError()
    for timestamp in (issued_at, expires_at):
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise AuthenticationError()
    if expires_at <= issued_at:
        raise AuthenticationError()

    return TokenPayload(
        subject=subject,
        token_version=version,
        jwt_id=jwt_id,
        issued_at=datetime.fromtimestamp(issued_at, tz=timezone.utc),
        expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
    )
