"""Password strength policy for CohortIQ AI accounts.

Returned problems describe the rule that failed and never include the password.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.app.core.security import MAX_PASSWORD_LENGTH

MIN_PASSWORD_LENGTH = 12
PASSPHRASE_LENGTH = 20
MIN_DISTINCT_CHARACTERS = 6
MIN_EMAIL_NAME_LENGTH_TO_CHECK = 4

_COMMON_FRAGMENTS = (
    "password",
    "passw0rd",
    "p@ssword",
    "qwerty",
    "123456",
    "abcdef",
    "letmein",
    "welcome",
    "admin",
    "cohortiq",
    "changeme",
)


def validate_password_strength(password: Any, *, email: Optional[str] = None) -> list[str]:
    """Return a list of policy problems; an empty list means the password is acceptable.

    Rules: 12-1024 characters; at least three of lowercase, uppercase, digits
    and symbols (or a passphrase of 20+ characters); at least 6 distinct
    characters; no common words such as "password"; and not containing the
    name part of the account's email address.
    """
    if not isinstance(password, str):
        return ["Password must be text."]

    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"Password must be at most {MAX_PASSWORD_LENGTH} characters long.")
    if not password.strip():
        problems.append("Password must not be blank.")
        return problems

    character_classes = sum(
        (
            any(ch.islower() for ch in password),
            any(ch.isupper() for ch in password),
            any(ch.isdigit() for ch in password),
            any(not ch.isalnum() for ch in password),
        )
    )
    if len(password) < PASSPHRASE_LENGTH and character_classes < 3:
        problems.append(
            "Password must use at least three of: lowercase letters, uppercase letters, digits, "
            f"symbols (or be a passphrase of at least {PASSPHRASE_LENGTH} characters)."
        )
    if len(set(password)) < MIN_DISTINCT_CHARACTERS:
        problems.append("Password is too repetitive.")

    lowered = password.lower()
    if any(fragment in lowered for fragment in _COMMON_FRAGMENTS):
        problems.append("Password must not contain common words or sequences such as 'password' or '123456'.")
    if email and "@" in email:
        name = email.split("@", 1)[0].lower()
        if len(name) >= MIN_EMAIL_NAME_LENGTH_TO_CHECK and name in lowered:
            problems.append("Password must not contain the account's email name.")
    return problems
