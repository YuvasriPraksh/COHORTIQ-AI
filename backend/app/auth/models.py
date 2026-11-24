"""Authentication data types shared by the repository and the API dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

ROLE_STUDENT = "student"
ROLE_ADMINISTRATOR = "administrator"
ROLES = (ROLE_STUDENT, ROLE_ADMINISTRATOR)


@dataclass(frozen=True)
class AuthenticatedUser:
    """An authenticated account as loaded from the user store.

    Contains no secrets: no password hash and no token.
    """

    id: str
    role: str
    is_active: bool
    token_version: int
    email: Optional[str] = None
    admission_batch: Optional[str] = None
    programme: Optional[str] = None
