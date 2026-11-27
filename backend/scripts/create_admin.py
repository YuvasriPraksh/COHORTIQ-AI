"""Create a CohortIQ AI administrator account from the command line.

Usage (from the project root, with the virtual environment active)::

    python -m backend.scripts.create_admin [--email EMAIL] [--full-name NAME] [--db-path PATH]

Security behaviour
- The password is read with a hidden prompt and must be entered twice. There is
  deliberately no command-line option for it, so it never appears in shell
  history or process listings.
- The script refuses to run without an interactive terminal, so a password
  cannot be piped in or echoed.
- The password must satisfy the account password policy.
- An existing account with the same email (any letter case, any role) is never
  modified or upgraded; the script stops instead.
- Passwords and password hashes are never printed or logged.
- This is the only way to create an administrator; the API has no public
  endpoint for it.
- The new account and a ``user.created`` audit event (actor ``cli``, role
  only; no email, name or password) are stored in one transaction.
"""

from __future__ import annotations

import argparse
import getpass
import hmac
import sqlite3
import sys
from pathlib import Path
from typing import Callable, Optional, TextIO

from app.config import ensure_app_directories, get_settings
from app.database import init_database
from backend.app.audit.repository import AuditEventError, init_audit_tables
from backend.app.auth.password_policy import validate_password_strength
from backend.app.auth.repository import (
    DuplicateEmailError,
    WeakPasswordError,
    create_bootstrap_administrator,
    get_user_by_email,
    init_auth_tables,
    normalize_email,
)

MAX_PASSWORD_ATTEMPTS = 3

EXIT_OK = 0
EXIT_FAILED = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.scripts.create_admin",
        description=(
            "Create a CohortIQ AI administrator account. The password is always "
            "entered at a hidden prompt; it cannot be passed as an argument."
        ),
        allow_abbrev=False,
    )
    parser.add_argument("--email", help="Administrator email address (prompted for if omitted).")
    parser.add_argument("--full-name", dest="full_name", help="Optional display name.")
    parser.add_argument(
        "--db-path",
        dest="db_path",
        help="SQLite database file. Defaults to DATABASE_PATH from the application configuration.",
    )
    return parser


def _initialize_database(db_path: Optional[str]) -> Path:
    """Create the regulation, users and audit tables if needed (same as API startup)."""
    if db_path:
        path = Path(db_path)
    else:
        path = Path(ensure_app_directories(get_settings()).database_path)
    init_database(path)
    init_auth_tables(path)
    init_audit_tables(path)
    return path


def _prompt_new_password(
    read_password: Callable[[str], str], email: str, err: TextIO
) -> Optional[str]:
    for _ in range(MAX_PASSWORD_ATTEMPTS):
        password = read_password("Password: ")
        problems = validate_password_strength(password, email=email)
        if problems:
            print("Password rejected:", file=err)
            for problem in problems:
                print(f"  - {problem}", file=err)
            continue
        confirmation = read_password("Confirm password: ")
        if not hmac.compare_digest(password.encode("utf-8"), confirmation.encode("utf-8")):
            print("Passwords do not match.", file=err)
            continue
        return password
    print("Too many unsuccessful attempts. No account was created.", file=err)
    return None


def main(
    argv: Optional[list[str]] = None,
    *,
    read_password: Callable[[str], str] = getpass.getpass,
    read_line: Callable[[str], str] = input,
    is_interactive: Optional[Callable[[], bool]] = None,
    out: Optional[TextIO] = None,
    err: Optional[TextIO] = None,
) -> int:
    """Run the command. Returns a process exit code."""
    args = build_parser().parse_args(argv)
    out = out or sys.stdout
    err = err or sys.stderr

    interactive = is_interactive() if is_interactive is not None else sys.stdin.isatty()
    if not interactive:
        print(
            "Error: this command must be run in an interactive terminal so the password "
            "can be entered at a hidden prompt.",
            file=err,
        )
        return EXIT_FAILED

    try:
        raw_email = args.email if args.email is not None else read_line("Administrator email: ")
        try:
            email = normalize_email(raw_email)
        except ValueError:
            print("Error: the email address is not valid.", file=err)
            return EXIT_FAILED

        db_path = _initialize_database(args.db_path)
        if get_user_by_email(email, db_path=db_path) is not None:
            print("Error: an account with this email already exists. No account was created.", file=err)
            return EXIT_FAILED

        password = _prompt_new_password(read_password, email, err)
        if password is None:
            return EXIT_FAILED

        # The account and its audit event are written in one transaction.
        user = create_bootstrap_administrator(email, password, full_name=args.full_name, db_path=db_path)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. No account was created.", file=err)
        return EXIT_FAILED
    except DuplicateEmailError:
        print("Error: an account with this email already exists. No account was created.", file=err)
        return EXIT_FAILED
    except WeakPasswordError:
        print("Error: the password does not meet the password policy. No account was created.", file=err)
        return EXIT_FAILED
    except (sqlite3.Error, AuditEventError):
        # The account and its audit event are written in one transaction, so
        # nothing was stored. Details are not printed (they may include paths).
        print("Error: the account could not be stored. No account was created.", file=err)
        return EXIT_FAILED
    except ValueError as error:
        print(f"Error: {error} No account was created.", file=err)
        return EXIT_FAILED

    print(f"Administrator account created (id={user.id}, email={user.email}).", file=out)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised through a subprocess test
    sys.exit(main())
