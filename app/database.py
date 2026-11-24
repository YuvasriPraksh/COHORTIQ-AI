"""Database access utilities for CohortIQ AI.

This module manages SQLite storage for regulation metadata and extracted page
content. The database path is configurable through ``app.config``.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from app.config import get_settings

APPROVED_VERIFICATION_STATUSES = {
    "approved",
    "verified",
    "administrator_verified",
    "administrator_approved",
    "verified_and_approved",
}


def _resolve_database_path(db_path: str | Path | None = None) -> Path:
    """Resolve the SQLite database path using config unless overridden."""
    if db_path is None:
        return get_settings().database_path
    return Path(db_path)


def _to_iso_date_string(value: Any) -> str | None:
    """Convert date/datetime values to ISO strings; pass through other values."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _normalize_applicability(value: Any, field_name: str) -> str:
    """Normalize applicability values to a JSON array string for consistent storage."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{field_name} must be a JSON array string or a list/tuple of values."
            ) from exc
        if not isinstance(parsed, list):
            raise ValueError(f"{field_name} JSON value must be an array.")
        items = parsed
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        raise TypeError(f"{field_name} must be a list/tuple/set or a JSON array string.")

    normalized_items = [str(item) for item in items]
    return json.dumps(normalized_items, ensure_ascii=False)


def _deserialize_applicability(value: Any) -> list[str]:
    """Deserialize a stored applicability JSON array into a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [str(parsed)]
    return [str(value)]


def _row_to_regulation_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a regulation row to a plain dictionary with parsed applicability."""
    data = dict(row)
    data["applicable_batches"] = _deserialize_applicability(data.get("applicable_batches"))
    data["applicable_programmes"] = _deserialize_applicability(data.get("applicable_programmes"))
    return data


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Create and return a SQLite connection with foreign keys enabled.

    Args:
        db_path: Optional path to the SQLite database file. When omitted, the
            path from ``app.config.get_settings()`` is used.

    Returns:
        An open ``sqlite3.Connection`` configured with ``sqlite3.Row`` rows and
        ``PRAGMA foreign_keys = ON``.
    """
    database_path = _resolve_database_path(db_path)
    if database_path.parent and str(database_path.parent) not in ("", "."):
        database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def init_database(db_path: str | Path | None = None) -> None:
    """Create the SQLite database and required tables if they do not exist.

    This function also enables SQLite foreign-key enforcement for the session
    used to initialize the schema.

    Args:
        db_path: Optional path to the SQLite database file. When omitted, the
            path from ``app.config.get_settings()`` is used.
    """
    with closing(get_connection(db_path)) as connection:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS regulations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_name TEXT NOT NULL,
                regulation_version TEXT NOT NULL,
                effective_date TEXT,
                applicable_batches TEXT NOT NULL,
                applicable_programmes TEXT NOT NULL,
                upload_date TEXT NOT NULL,
                total_pages INTEGER,
                processing_status TEXT,
                verification_status TEXT
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS document_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                regulation_id INTEGER NOT NULL,
                page_number INTEGER NOT NULL,
                extracted_text TEXT,
                extraction_status TEXT,
                FOREIGN KEY (regulation_id) REFERENCES regulations(id) ON DELETE CASCADE
            );
            """
        )
        connection.commit()


def insert_regulation(
    metadata: Mapping[str, Any], db_path: str | Path | None = None
) -> int:
    """Insert regulation metadata and return the new regulation ID.

    Args:
        metadata: Mapping containing regulation metadata. Required keys are
            ``document_name``, ``regulation_version``, ``applicable_batches``,
            ``applicable_programmes``, and ``upload_date``. Optional keys are
            ``effective_date``, ``total_pages``, ``processing_status``, and
            ``verification_status``.
        db_path: Optional database path override.

    Returns:
        The newly created regulation row ID.

    Raises:
        KeyError: If a required metadata field is missing.
        TypeError/ValueError: If applicability values are not in a supported
            format.
    """
    regulation_values = _prepare_regulation_values(metadata)

    with closing(get_connection(db_path)) as connection:
        cursor = connection.cursor()
        regulation_id = _insert_regulation_row(cursor, regulation_values)
        connection.commit()
        return regulation_id


def insert_document_pages(
    regulation_id: int,
    pages: Sequence[Mapping[str, Any]],
    db_path: str | Path | None = None,
) -> None:
    """Insert extracted page records for a regulation within a transaction.

    Args:
        regulation_id: ID of the parent regulation record.
        pages: Sequence of page mappings. Each item should contain
            ``page_number`` and may contain ``text``/``extracted_text`` and
            ``status``/``extraction_status``.
        db_path: Optional database path override.
    """
    page_values = _prepare_page_values(pages)

    with closing(get_connection(db_path)) as connection:
        cursor = connection.cursor()
        cursor.execute("BEGIN;")
        try:
            _insert_page_rows(cursor, regulation_id, page_values)
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def insert_regulation_with_pages(
    metadata: Mapping[str, Any],
    pages: Sequence[Mapping[str, Any]],
    db_path: str | Path | None = None,
) -> int:
    """Atomically insert a regulation and all of its extracted pages.

    Both inserts run on one connection inside one transaction: either the
    regulation row and every page row are committed together, or nothing is
    saved. Metadata and pages are validated and normalized exactly as in
    ``insert_regulation`` and ``insert_document_pages`` before the transaction
    starts, so invalid input never touches the database.

    Args:
        metadata: Regulation metadata (same contract as ``insert_regulation``).
        pages: Page mappings (same contract as ``insert_document_pages``).
        db_path: Optional database path override.

    Returns:
        The newly created regulation row ID.

    Raises:
        Any validation error from metadata/page normalization, or any database
        error. On a database error the whole transaction is rolled back before
        the exception is re-raised.
    """
    regulation_values = _prepare_regulation_values(metadata)
    page_values = _prepare_page_values(pages)

    with closing(get_connection(db_path)) as connection:
        cursor = connection.cursor()
        cursor.execute("BEGIN;")
        try:
            regulation_id = _insert_regulation_row(cursor, regulation_values)
            _insert_page_rows(cursor, regulation_id, page_values)
            connection.commit()
        except BaseException:
            # Roll back on any failure (including interrupts) so no partial
            # regulation or page rows are ever persisted.
            connection.rollback()
            raise
        return regulation_id


_REGULATION_INSERT_SQL = """
    INSERT INTO regulations (
        document_name,
        regulation_version,
        effective_date,
        applicable_batches,
        applicable_programmes,
        upload_date,
        total_pages,
        processing_status,
        verification_status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

_PAGE_INSERT_SQL = """
    INSERT INTO document_pages (
        regulation_id, page_number, extracted_text, extraction_status
    ) VALUES (?, ?, ?, ?);
"""


def _prepare_regulation_values(metadata: Mapping[str, Any]) -> tuple[Any, ...]:
    """Validate and normalize regulation metadata into ordered insert values.

    Raises:
        KeyError: If a required metadata field is missing.
        TypeError/ValueError: If applicability values are not in a supported
            format or ``upload_date`` is None.
    """
    required_keys = (
        "document_name",
        "regulation_version",
        "applicable_batches",
        "applicable_programmes",
        "upload_date",
    )
    for key in required_keys:
        if key not in metadata:
            raise KeyError(f"Missing required regulation metadata field: {key}")

    document_name = str(metadata["document_name"])
    regulation_version = str(metadata["regulation_version"])
    effective_date = _to_iso_date_string(metadata.get("effective_date"))
    applicable_batches = _normalize_applicability(
        metadata["applicable_batches"], "applicable_batches"
    )
    applicable_programmes = _normalize_applicability(
        metadata["applicable_programmes"], "applicable_programmes"
    )
    upload_date = _to_iso_date_string(metadata["upload_date"])
    if upload_date is None:
        raise ValueError("upload_date cannot be None")
    total_pages = metadata.get("total_pages")
    processing_status = metadata.get("processing_status")
    verification_status = metadata.get("verification_status")

    return (
        document_name,
        regulation_version,
        effective_date,
        applicable_batches,
        applicable_programmes,
        upload_date,
        total_pages,
        processing_status,
        verification_status,
    )


def _prepare_page_values(
    pages: Sequence[Mapping[str, Any]],
) -> list[tuple[int, str | None, str | None]]:
    """Validate and normalize page mappings into (page_number, text, status) values."""
    page_values: list[tuple[int, str | None, str | None]] = []
    for page in pages:
        page_number = int(page["page_number"])
        extracted_text = page.get("extracted_text", page.get("text"))
        extraction_status = page.get("extraction_status", page.get("status"))
        page_values.append(
            (
                page_number,
                extracted_text if extracted_text is None else str(extracted_text),
                extraction_status if extraction_status is None else str(extraction_status),
            )
        )
    return page_values


def _insert_regulation_row(cursor: sqlite3.Cursor, regulation_values: tuple[Any, ...]) -> int:
    """Insert one prepared regulation row using the caller's cursor/transaction."""
    cursor.execute(_REGULATION_INSERT_SQL, regulation_values)
    return int(cursor.lastrowid)


def _insert_page_rows(
    cursor: sqlite3.Cursor,
    regulation_id: int,
    page_values: Sequence[tuple[int, str | None, str | None]],
) -> None:
    """Insert prepared page rows for a regulation using the caller's cursor/transaction."""
    cursor.executemany(
        _PAGE_INSERT_SQL,
        [(regulation_id, *values) for values in page_values],
    )


def get_all_regulations(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Return all stored regulations.

    Args:
        db_path: Optional database path override.

    Returns:
        A list of regulation dictionaries with applicability fields deserialized
        into Python lists.
    """
    with closing(get_connection(db_path)) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id, document_name, regulation_version, effective_date,
                   applicable_batches, applicable_programmes, upload_date,
                   total_pages, processing_status, verification_status
            FROM regulations
            ORDER BY id ASC;
            """
        )
        return [_row_to_regulation_dict(row) for row in cursor.fetchall()]


def get_regulation_by_id(
    regulation_id: int, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    """Retrieve a single regulation by ID.

    Args:
        regulation_id: Regulation primary key.
        db_path: Optional database path override.

    Returns:
        The regulation dictionary if found, otherwise ``None``.
    """
    with closing(get_connection(db_path)) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id, document_name, regulation_version, effective_date,
                   applicable_batches, applicable_programmes, upload_date,
                   total_pages, processing_status, verification_status
            FROM regulations
            WHERE id = ?;
            """,
            (regulation_id,),
        )
        row = cursor.fetchone()
        return _row_to_regulation_dict(row) if row else None


def _is_approved_verification_status(status: Any) -> bool:
    """Return True if a verification status represents verified/approved evidence."""
    if status is None:
        return False
    return str(status).strip().lower() in APPROVED_VERIFICATION_STATUSES


def get_applicable_regulations(
    admission_batch: str,
    programme: str,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Retrieve administrator-verified and approved regulations for a cohort.

    Only regulations with an approved/verified verification status are returned.
    Applicability is matched by checking that the supplied admission batch and
    programme are present in the regulation's stored applicability lists. The
    function does not automatically select the latest regulation.

    Args:
        admission_batch: Admission batch/cohort identifier to match.
        programme: Programme identifier to match.
        db_path: Optional database path override.

    Returns:
        A list of matching regulation dictionaries.
    """
    batch_value = str(admission_batch)
    programme_value = str(programme)

    with closing(get_connection(db_path)) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id, document_name, regulation_version, effective_date,
                   applicable_batches, applicable_programmes, upload_date,
                   total_pages, processing_status, verification_status
            FROM regulations
            ORDER BY id ASC;
            """
        )
        rows = cursor.fetchall()

    matches: list[dict[str, Any]] = []
    for row in rows:
        if not _is_approved_verification_status(row["verification_status"]):
            continue
        regulation = _row_to_regulation_dict(row)
        if (
            batch_value in regulation["applicable_batches"]
            and programme_value in regulation["applicable_programmes"]
        ):
            matches.append(regulation)
    return matches


def get_document_pages(
    regulation_id: int, db_path: str | Path | None = None
) -> list[dict[str, Any]]:
    """Return stored document pages for a regulation in ascending page order.

    Args:
        regulation_id: Regulation primary key.
        db_path: Optional database path override.

    Returns:
        A list of page dictionaries ordered by ``page_number`` ascending.
    """
    with closing(get_connection(db_path)) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id, regulation_id, page_number, extracted_text, extraction_status
            FROM document_pages
            WHERE regulation_id = ?
            ORDER BY page_number ASC, id ASC;
            """,
            (regulation_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def update_regulation_verification_status(
    regulation_id: int,
    verification_status: str | None,
    db_path: str | Path | None = None,
) -> bool:
    """Explicitly update the verification status of a regulation.

    The status is set exactly to the value supplied by the caller. This function
    does not automatically approve regulations (for example, after extraction).

    Args:
        regulation_id: Regulation primary key to update.
        verification_status: Verification status to store (e.g. approved,
            pending, rejected, unverified). The caller controls this value.
        db_path: Optional database path override.

    Returns:
        ``True`` if an existing regulation was updated, otherwise ``False`` when
        the regulation ID does not exist.
    """
    status_value = None if verification_status is None else str(verification_status)

    with closing(get_connection(db_path)) as connection:
        cursor = connection.cursor()
        cursor.execute("BEGIN;")
        try:
            cursor.execute(
                "UPDATE regulations SET verification_status = ? WHERE id = ?;",
                (status_value, regulation_id),
            )
            updated = cursor.rowcount > 0
            connection.commit()
            return updated
        except Exception:
            connection.rollback()
            raise


def delete_regulation(regulation_id: int, db_path: str | Path | None = None) -> bool:
    """Delete a regulation and its associated document pages safely.

    Args:
        regulation_id: Regulation primary key to delete.
        db_path: Optional database path override.

    Returns:
        ``True`` if a regulation record was deleted, otherwise ``False``.
    """
    with closing(get_connection(db_path)) as connection:
        cursor = connection.cursor()
        cursor.execute("BEGIN;")
        try:
            cursor.execute(
                "DELETE FROM document_pages WHERE regulation_id = ?;",
                (regulation_id,),
            )
            cursor.execute("DELETE FROM regulations WHERE id = ?;", (regulation_id,))
            deleted = cursor.rowcount > 0
            connection.commit()
            return deleted
        except Exception:
            connection.rollback()
            raise

