"""Authentication foundation (Part 4.2, Stage 1): passwords, JWTs and configuration.

Signing secrets are generated at runtime for each test; none are hard-coded.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import inspect
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pytest
from argon2 import PasswordHasher

from backend.app.core import security
from backend.app.core.config import (
    DEFAULT_JWT_AUDIENCE,
    DEFAULT_JWT_ISSUER,
    MIN_JWT_SECRET_BYTES,
    Settings,
    get_settings,
)
from backend.app.core.security import (
    GENERIC_AUTHENTICATION_ERROR,
    JWT_ALGORITHM,
    MAX_PASSWORD_LENGTH,
    MAX_TOKEN_LENGTH,
    REQUIRED_TOKEN_CLAIMS,
    AuthConfigurationError,
    AuthenticationError,
    TokenPayload,
    create_access_token,
    decode_access_token,
    hash_password,
    password_needs_rehash,
    perform_dummy_password_check,
    verify_password,
)

AUTH_ENV_VARS = (
    "APP_ENV",
    "JWT_SECRET_KEY",
    "JWT_ISSUER",
    "JWT_AUDIENCE",
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "JWT_LEEWAY_SECONDS",
)


@pytest.fixture(autouse=True)
def _clean_auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test from auth settings in the developer's environment."""
    for name in AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _strong_secret() -> str:
    return secrets.token_urlsafe(48)


@pytest.fixture
def settings() -> Settings:
    return Settings(app_env="test", jwt_secret_key=_strong_secret())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _claims(**overrides: Any) -> dict[str, Any]:
    now = _now()
    claims: dict[str, Any] = {
        "sub": "42",
        "ver": 0,
        "jti": secrets.token_hex(16),
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=30),
        "iss": DEFAULT_JWT_ISSUER,
        "aud": DEFAULT_JWT_AUDIENCE,
    }
    claims.update(overrides)
    return claims


def _sign(claims: dict[str, Any], secret: str, algorithm: str = JWT_ALGORITHM) -> str:
    return jwt.encode(claims, secret, algorithm=algorithm)


def _b64(data: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).rstrip(b"=").decode()


def _b64_decode(segment: str) -> dict[str, Any]:
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def _assert_rejected(token: Any, settings: Settings) -> None:
    with pytest.raises(AuthenticationError) as excinfo:
        decode_access_token(token, settings=settings)
    assert str(excinfo.value) == GENERIC_AUTHENTICATION_ERROR
    if isinstance(token, str) and token:
        assert token not in str(excinfo.value)
    assert settings.jwt_secret_key not in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #


def test_password_hash_is_argon2id_with_policy_parameters() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert "correct horse battery staple" not in password_hash


def test_password_hashes_are_salted() -> None:
    first = hash_password("same password")
    second = hash_password("same password")

    assert first != second
    assert verify_password("same password", first)
    assert verify_password("same password", second)


@pytest.mark.parametrize("password", ["Tr1cky-P@ss", "pässwörd🔒", " leading and trailing ", "x" * MAX_PASSWORD_LENGTH])
def test_password_verification_round_trip(password: str) -> None:
    password_hash = hash_password(password)

    assert verify_password(password, password_hash) is True


@pytest.mark.parametrize("attempt", ["Tr1cky-P@sS", "Tr1cky-P@ss ", " Tr1cky-P@ss", "", "tr1cky-p@ss"])
def test_wrong_passwords_are_rejected(attempt: str) -> None:
    assert verify_password(attempt, hash_password("Tr1cky-P@ss")) is False


@pytest.mark.parametrize(
    "stored_hash",
    [
        "",
        "not-a-hash",
        "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ01234",
        "$argon2id$v=19$m=65536,t=3,p=4$corrupted",
        "Tr1cky-P@ss",
    ],
)
def test_malformed_or_foreign_hashes_never_verify(stored_hash: str) -> None:
    assert verify_password("Tr1cky-P@ss", stored_hash) is False


@pytest.mark.parametrize("password", [None, 123, b"bytes", ["list"]])
def test_non_string_passwords_never_verify(password: Any) -> None:
    assert verify_password(password, hash_password("valid")) is False


@pytest.mark.parametrize("password", ["", None, 123, "x" * (MAX_PASSWORD_LENGTH + 1)])
def test_hash_password_rejects_invalid_input(password: Any) -> None:
    with pytest.raises(ValueError):
        hash_password(password)


def test_password_needs_rehash() -> None:
    assert password_needs_rehash(hash_password("current policy")) is False
    weaker = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash("old policy")
    assert password_needs_rehash(weaker) is True
    assert password_needs_rehash("not-a-hash") is True


def test_dummy_password_check_always_fails_and_uses_argon2id() -> None:
    assert perform_dummy_password_check("anything") is False
    assert perform_dummy_password_check(None) is False
    assert security._dummy_password_hash is not None
    assert security._dummy_password_hash.startswith("$argon2id$")


# --------------------------------------------------------------------------- #
# Token creation
# --------------------------------------------------------------------------- #


def test_created_token_has_all_required_claims_and_no_role(settings: Settings) -> None:
    token = create_access_token("42", 3, settings=settings)

    header = jwt.get_unverified_header(token)
    assert header == {"alg": "HS256", "typ": "JWT"}
    claims = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )
    assert set(claims) == set(REQUIRED_TOKEN_CLAIMS)
    assert "role" not in claims
    assert claims["sub"] == "42" and claims["ver"] == 3
    assert claims["iss"] == DEFAULT_JWT_ISSUER and claims["aud"] == DEFAULT_JWT_AUDIENCE
    assert claims["iat"] == claims["nbf"]
    assert claims["exp"] - claims["iat"] == 30 * 60
    assert len(claims["jti"]) == 32


def test_token_round_trip(settings: Settings) -> None:
    payload = decode_access_token(create_access_token(7, 2, settings=settings), settings=settings)

    assert isinstance(payload, TokenPayload)
    assert payload.subject == "7"
    assert payload.token_version == 2
    assert payload.expires_at - payload.issued_at == timedelta(minutes=30)


def test_every_token_has_a_unique_jwt_id(settings: Settings) -> None:
    ids = {decode_access_token(create_access_token("1", 0, settings=settings), settings=settings).jwt_id for _ in range(20)}
    assert len(ids) == 20


def test_custom_lifetime_is_honoured(settings: Settings) -> None:
    payload = decode_access_token(
        create_access_token("1", 0, settings=settings, expires_delta=timedelta(minutes=5)), settings=settings
    )
    assert payload.expires_at - payload.issued_at == timedelta(minutes=5)


def test_create_access_token_has_no_role_parameter(settings: Settings) -> None:
    assert "role" not in inspect.signature(create_access_token).parameters
    with pytest.raises(TypeError):
        create_access_token("1", 0, settings=settings, role="administrator")  # type: ignore[call-arg]


@pytest.mark.parametrize("subject", ["", "   ", None, True, 1.5, ["1"]])
def test_create_access_token_rejects_invalid_subjects(settings: Settings, subject: Any) -> None:
    with pytest.raises(ValueError):
        create_access_token(subject, 0, settings=settings)


@pytest.mark.parametrize("version", [-1, True, "1", 1.0, None])
def test_create_access_token_rejects_invalid_token_versions(settings: Settings, version: Any) -> None:
    with pytest.raises(ValueError):
        create_access_token("1", version, settings=settings)


@pytest.mark.parametrize("lifetime", [timedelta(0), timedelta(seconds=-1)])
def test_create_access_token_rejects_non_positive_lifetimes(settings: Settings, lifetime: timedelta) -> None:
    with pytest.raises(ValueError):
        create_access_token("1", 0, settings=settings, expires_delta=lifetime)


# --------------------------------------------------------------------------- #
# Token validation: expiry and timing claims
# --------------------------------------------------------------------------- #


def test_expired_token_is_rejected(settings: Settings) -> None:
    issued = _now() - timedelta(minutes=30, seconds=settings.jwt_leeway_seconds + 5)
    _assert_rejected(create_access_token("1", 0, settings=settings, now=issued), settings)


def test_token_within_clock_leeway_is_accepted(settings: Settings) -> None:
    issued = _now() - timedelta(minutes=30, seconds=10)
    assert decode_access_token(create_access_token("1", 0, settings=settings, now=issued), settings=settings)


def test_not_yet_valid_token_is_rejected(settings: Settings) -> None:
    future = _now() + timedelta(minutes=5)
    _assert_rejected(_sign(_claims(nbf=future), settings.jwt_secret_key), settings)


def test_token_issued_in_the_future_is_rejected(settings: Settings) -> None:
    future = _now() + timedelta(minutes=5)
    _assert_rejected(_sign(_claims(iat=future, nbf=_now()), settings.jwt_secret_key), settings)


def test_token_expiring_before_it_was_issued_is_rejected(settings: Settings) -> None:
    now = _now()
    _assert_rejected(_sign(_claims(iat=now, exp=now), settings.jwt_secret_key), settings)


# --------------------------------------------------------------------------- #
# Token validation: malformed, tampered and incorrectly signed tokens
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "token",
    ["", "abc", "a.b", "a.b.c", "....", "Bearer x.y.z", "x" * (MAX_TOKEN_LENGTH + 1), None, 123, b"a.b.c"],
    ids=["empty", "word", "two_parts", "garbage_parts", "dots", "bearer_prefix", "oversized", "none", "int", "bytes"],
)
def test_malformed_tokens_are_rejected(settings: Settings, token: Any) -> None:
    _assert_rejected(token, settings)


def test_tampered_payload_is_rejected(settings: Settings) -> None:
    header, payload, signature = create_access_token("1", 0, settings=settings).split(".")
    claims = _b64_decode(payload)
    claims["sub"] = "2"  # try to become another user
    _assert_rejected(".".join([header, _b64(claims), signature]), settings)


def test_tampered_signature_is_rejected(settings: Settings) -> None:
    header, payload, signature = create_access_token("1", 0, settings=settings).split(".")
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    _assert_rejected(".".join([header, payload, flipped]), settings)


def test_token_signed_with_another_secret_is_rejected(settings: Settings) -> None:
    _assert_rejected(_sign(_claims(), _strong_secret()), settings)


def test_token_with_role_claim_is_accepted_but_role_is_ignored(settings: Settings) -> None:
    token = _sign(_claims(role="administrator", is_admin=True), settings.jwt_secret_key)

    payload = decode_access_token(token, settings=settings)

    assert not hasattr(payload, "role")
    assert {f.name for f in dataclasses.fields(TokenPayload)} == {
        "subject", "token_version", "jwt_id", "issued_at", "expires_at"
    }


# --------------------------------------------------------------------------- #
# Token validation: algorithms
# --------------------------------------------------------------------------- #


def test_unsigned_alg_none_token_is_rejected(settings: Settings) -> None:
    token = _b64({"alg": "none", "typ": "JWT"}) + "." + _b64(
        {k: (int(v.timestamp()) if isinstance(v, datetime) else v) for k, v in _claims().items()}
    ) + "."
    _assert_rejected(token, settings)


@pytest.mark.parametrize("algorithm", ["HS384", "HS512"])
def test_other_hmac_algorithms_are_rejected(settings: Settings, algorithm: str) -> None:
    _assert_rejected(_sign(_claims(), settings.jwt_secret_key, algorithm=algorithm), settings)


@pytest.mark.parametrize("declared", ["RS256", "ES256", "hs256", "none", "None"])
def test_forged_algorithm_header_is_rejected(settings: Settings, declared: str) -> None:
    """Header claims another algorithm but carries a valid HS256 signature (confusion attack)."""
    claims = {k: (int(v.timestamp()) if isinstance(v, datetime) else v) for k, v in _claims().items()}
    signing_input = _b64({"alg": declared, "typ": "JWT"}) + "." + _b64(claims)
    signature = hmac.new(settings.jwt_secret_key.encode(), signing_input.encode(), hashlib.sha256).digest()
    token = signing_input + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    _assert_rejected(token, settings)


def test_algorithm_is_fixed_in_code() -> None:
    assert JWT_ALGORITHM == "HS256"
    assert not any("algorithm" in f.name for f in dataclasses.fields(Settings))


# --------------------------------------------------------------------------- #
# Token validation: issuer, audience and required claims
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "overrides",
    [{"iss": "another-issuer"}, {"iss": ""}, {"aud": "another-audience"}, {"aud": ["another-audience"]}, {"aud": ""}],
    ids=["wrong_iss", "empty_iss", "wrong_aud", "wrong_aud_list", "empty_aud"],
)
def test_wrong_issuer_or_audience_is_rejected(settings: Settings, overrides: dict[str, Any]) -> None:
    _assert_rejected(_sign(_claims(**overrides), settings.jwt_secret_key), settings)


@pytest.mark.parametrize("claim", REQUIRED_TOKEN_CLAIMS)
def test_missing_required_claim_is_rejected(settings: Settings, claim: str) -> None:
    claims = _claims()
    del claims[claim]
    _assert_rejected(_sign(claims, settings.jwt_secret_key), settings)


@pytest.mark.parametrize(
    "overrides",
    [
        {"sub": 42},
        {"sub": ""},
        {"sub": "   "},
        {"ver": "0"},
        {"ver": True},
        {"ver": -1},
        {"ver": 1.5},
        {"ver": None},
        {"jti": ""},
        {"jti": 5},
    ],
    ids=["sub_int", "sub_empty", "sub_blank", "ver_str", "ver_bool", "ver_negative", "ver_float", "ver_null", "jti_empty", "jti_int"],
)
def test_invalid_claim_types_are_rejected(settings: Settings, overrides: dict[str, Any]) -> None:
    _assert_rejected(_sign(_claims(**overrides), settings.jwt_secret_key), settings)


def test_tokens_from_custom_issuer_and_audience_settings() -> None:
    custom = Settings(app_env="test", jwt_secret_key=_strong_secret(), jwt_issuer="uni-api", jwt_audience="uni-web")

    token = create_access_token("1", 0, settings=custom)

    assert decode_access_token(token, settings=custom).subject == "1"
    default_issuer = dataclasses.replace(custom, jwt_issuer=DEFAULT_JWT_ISSUER)
    _assert_rejected(token, default_issuer)


# --------------------------------------------------------------------------- #
# Missing signing configuration
# --------------------------------------------------------------------------- #


def test_token_operations_require_a_configured_secret() -> None:
    unconfigured = Settings(app_env="development")
    assert unconfigured.jwt_secret_key is None

    with pytest.raises(AuthConfigurationError):
        create_access_token("1", 0, settings=unconfigured)
    with pytest.raises(AuthConfigurationError):
        decode_access_token("a.b.c", settings=unconfigured)


def test_weak_secret_is_refused_even_if_settings_were_bypassed(settings: Settings) -> None:
    object.__setattr__(settings, "jwt_secret_key", "short")

    with pytest.raises(AuthConfigurationError) as excinfo:
        create_access_token("1", 0, settings=settings)
    assert "short" not in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Configuration validation
# --------------------------------------------------------------------------- #


def test_authentication_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = get_settings()

    assert configured.app_env == "development"
    assert configured.jwt_secret_key is None
    assert configured.jwt_issuer == DEFAULT_JWT_ISSUER
    assert configured.jwt_audience == DEFAULT_JWT_AUDIENCE
    assert configured.access_token_expire_minutes == 30
    assert configured.jwt_leeway_seconds == 30
    assert configured.is_production is False


@pytest.mark.parametrize("environment", ["development", "test"])
def test_secret_is_optional_outside_production(monkeypatch: pytest.MonkeyPatch, environment: str) -> None:
    monkeypatch.setenv("APP_ENV", environment)
    assert get_settings().jwt_secret_key is None


@pytest.mark.parametrize("value", [None, "", "   "])
def test_production_requires_a_secret(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    if value is not None:
        monkeypatch.setenv("JWT_SECRET_KEY", value)

    with pytest.raises(ValueError, match="JWT_SECRET_KEY is required in production"):
        get_settings()


def test_production_accepts_a_strong_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = _strong_secret()
    monkeypatch.setenv("APP_ENV", "PRODUCTION")
    monkeypatch.setenv("JWT_SECRET_KEY", f"  {secret}\n")

    configured = get_settings()

    assert configured.is_production
    assert configured.jwt_secret_key == secret  # surrounding whitespace removed


def _weak_secrets() -> list[Any]:
    random_tail = secrets.token_urlsafe(40)
    return [
        pytest.param("x" * (MIN_JWT_SECRET_BYTES - 1), id="too_short"),
        pytest.param(secrets.token_urlsafe(16), id="random_but_short"),
        pytest.param("a" * 64, id="single_character"),
        pytest.param("ab" * 32, id="two_characters"),
        pytest.param("change-me-" + random_tail, id="placeholder_change_me"),
        pytest.param("your-secret-key-" + random_tail, id="placeholder_your_secret"),
        pytest.param("REPLACE_ME_" + random_tail, id="placeholder_replace_me"),
        pytest.param("example-" + random_tail, id="placeholder_example"),
    ]


@pytest.mark.parametrize("environment", ["development", "test", "production"])
@pytest.mark.parametrize("secret", _weak_secrets())
def test_weak_secrets_are_rejected_in_every_environment(
    monkeypatch: pytest.MonkeyPatch, environment: str, secret: str
) -> None:
    monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.setenv("JWT_SECRET_KEY", secret)

    with pytest.raises(ValueError, match="JWT_SECRET_KEY") as excinfo:
        get_settings()
    assert secret not in str(excinfo.value)


def test_secret_is_never_shown_in_settings_repr() -> None:
    secret = _strong_secret()
    configured = Settings(app_env="test", jwt_secret_key=secret)

    assert secret not in repr(configured)
    assert secret not in str(configured)


@pytest.mark.parametrize("value", ["staging", "prod", "dev", "1"])
def test_unknown_app_environment_is_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("APP_ENV", value)
    with pytest.raises(ValueError, match="APP_ENV"):
        get_settings()


@pytest.mark.parametrize(
    ("name", "value", "valid"),
    [
        ("ACCESS_TOKEN_EXPIRE_MINUTES", "0", False),
        ("ACCESS_TOKEN_EXPIRE_MINUTES", "1", True),
        ("ACCESS_TOKEN_EXPIRE_MINUTES", "1440", True),
        ("ACCESS_TOKEN_EXPIRE_MINUTES", "1441", False),
        ("ACCESS_TOKEN_EXPIRE_MINUTES", "-5", False),
        ("ACCESS_TOKEN_EXPIRE_MINUTES", "thirty", False),
        ("JWT_LEEWAY_SECONDS", "-1", False),
        ("JWT_LEEWAY_SECONDS", "0", True),
        ("JWT_LEEWAY_SECONDS", "300", True),
        ("JWT_LEEWAY_SECONDS", "301", False),
        ("JWT_LEEWAY_SECONDS", "1.5", False),
    ],
)
def test_bounded_authentication_settings(monkeypatch: pytest.MonkeyPatch, name: str, value: str, valid: bool) -> None:
    monkeypatch.setenv(name, value)
    if valid:
        assert str(getattr(get_settings(), name.lower())) == value
    else:
        with pytest.raises(ValueError, match=name):
            get_settings()


def test_blank_issuer_and_audience_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_ISSUER", "   ")
    monkeypatch.setenv("JWT_AUDIENCE", "")

    configured = get_settings()

    assert configured.jwt_issuer == DEFAULT_JWT_ISSUER
    assert configured.jwt_audience == DEFAULT_JWT_AUDIENCE


@pytest.mark.parametrize("field", ["jwt_issuer", "jwt_audience"])
@pytest.mark.parametrize("value", ["", "  ", " padded "])
def test_invalid_issuer_or_audience_values_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ValueError, match="JWT_ISSUER|JWT_AUDIENCE"):
        Settings(**{field: value})


def test_issuer_and_audience_come_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_ISSUER", "cohortiq-prod-api")
    monkeypatch.setenv("JWT_AUDIENCE", "cohortiq-web")

    configured = get_settings()

    assert (configured.jwt_issuer, configured.jwt_audience) == ("cohortiq-prod-api", "cohortiq-web")
