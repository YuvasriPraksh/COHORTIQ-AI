"""Role-specific institutional email domains."""

from __future__ import annotations

from backend.app.auth.models import ROLE_ADMINISTRATOR, ROLE_STAFF, ROLE_STUDENT
from backend.app.core.config import Settings

LEGACY_STUDENT_EMAIL_DOMAIN = "smvec.ac.in"


def email_domain_for_role(role: str, settings: Settings) -> str:
    """Return the configured email domain for a persisted role."""
    domains = {
        ROLE_STUDENT: settings.student_email_domain,
        ROLE_STAFF: settings.staff_email_domain,
        ROLE_ADMINISTRATOR: settings.administrator_email_domain,
    }
    try:
        return domains[role]
    except KeyError:
        raise ValueError("An email domain is not configured for this role.") from None


def email_matches_role_domain(
    email: str,
    role: str,
    settings: Settings,
    *,
    allow_legacy_student: bool = False,
) -> bool:
    """Compare the normalized address domain to the role's configured domain."""
    domain = email.rpartition("@")[2].lower()
    if domain == email_domain_for_role(role, settings):
        return True
    return allow_legacy_student and role == ROLE_STUDENT and domain == LEGACY_STUDENT_EMAIL_DOMAIN
