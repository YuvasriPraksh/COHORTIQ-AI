"""Tests for the SQLite database layer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.database import (
    delete_regulation,
    get_all_regulations,
    get_applicable_regulations,
    get_connection,
    get_document_pages,
    get_regulation_by_id,
    init_database,
    insert_document_pages,
    insert_regulation,
    update_regulation_verification_status,
)


def _sample_metadata(**overrides):
    """Build sample regulation metadata for tests."""
    metadata = {
        "document_name": "Academic Regulations 2024",
        "regulation_version": "v1",
        "effective_date": "2024-08-01",
        "applicable_batches": ["2023", "2024"],
        "applicable_programmes": ["BSc Computer Science", "BSc AI"],
        "upload_date": "2024-07-15",
        "total_pages": 2,
        "processing_status": "processed",
        "verification_status": "approved",
    }
    metadata.update(overrides)
    return metadata


def test_init_database_creates_tables(tmp_path: Path) -> None:
    """Initializes the database file and required tables."""
    db_path = tmp_path / "cohortiq.db"

    init_database(db_path)

    assert db_path.exists()
    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        }
    assert "regulations" in tables
    assert "document_pages" in tables


def test_insert_and_get_regulation(tmp_path: Path) -> None:
    """Inserts regulation metadata and retrieves it by ID and in listings."""
    db_path = tmp_path / "cohortiq.db"
    init_database(db_path)

    regulation_id = insert_regulation(_sample_metadata(), db_path=db_path)

    assert isinstance(regulation_id, int)
    regulation = get_regulation_by_id(regulation_id, db_path=db_path)
    assert regulation is not None
    assert regulation["id"] == regulation_id
    assert regulation["document_name"] == "Academic Regulations 2024"
    assert regulation["regulation_version"] == "v1"
    assert regulation["effective_date"] == "2024-08-01"
    assert regulation["upload_date"] == "2024-07-15"
    assert regulation["total_pages"] == 2
    assert regulation["processing_status"] == "processed"
    assert regulation["verification_status"] == "approved"
    # Applicability is stored consistently and returned as structured lists.
    assert regulation["applicable_batches"] == ["2023", "2024"]
    assert regulation["applicable_programmes"] == ["BSc Computer Science", "BSc AI"]

    all_regulations = get_all_regulations(db_path=db_path)
    assert len(all_regulations) == 1
    assert all_regulations[0]["id"] == regulation_id


def test_insert_document_pages_preserves_page_numbers_and_order(tmp_path: Path) -> None:
    """Stores extracted pages, preserves original page numbers, and returns ordered pages."""
    db_path = tmp_path / "cohortiq.db"
    init_database(db_path)
    regulation_id = insert_regulation(_sample_metadata(), db_path=db_path)

    pages = [
        {
            "page_number": 2,
            "text": "Page two text",
            "status": "success",
        },
        {
            "page_number": 1,
            "text": "",
            "status": "needs_ocr_or_manual_inspection",
        },
        {
            "page_number": 3,
            "text": "Page three text",
            "status": "success",
        },
    ]
    insert_document_pages(regulation_id, pages, db_path=db_path)

    stored_pages = get_document_pages(regulation_id, db_path=db_path)
    assert [page["page_number"] for page in stored_pages] == [1, 2, 3]
    assert stored_pages[0]["regulation_id"] == regulation_id
    assert stored_pages[0]["extracted_text"] == ""
    assert stored_pages[0]["extraction_status"] == "needs_ocr_or_manual_inspection"
    assert stored_pages[1]["extracted_text"] == "Page two text"
    assert stored_pages[1]["extraction_status"] == "success"
    assert stored_pages[2]["extracted_text"] == "Page three text"


def test_get_applicable_regulations_filters_verified_and_matching(tmp_path: Path) -> None:
    """Returns only verified/approved regulations matching batch and programme."""
    db_path = tmp_path / "cohortiq.db"
    init_database(db_path)

    matching_id = insert_regulation(
        _sample_metadata(
            document_name="CS 2024",
            regulation_version="v1",
            applicable_batches=["2024"],
            applicable_programmes=["BSc Computer Science"],
            verification_status="approved",
        ),
        db_path=db_path,
    )
    insert_regulation(
        _sample_metadata(
            document_name="Unverified CS 2024",
            applicable_batches=["2024"],
            applicable_programmes=["BSc Computer Science"],
            verification_status="pending",
        ),
        db_path=db_path,
    )
    insert_regulation(
        _sample_metadata(
            document_name="Wrong batch",
            applicable_batches=["2023"],
            applicable_programmes=["BSc Computer Science"],
            verification_status="approved",
        ),
        db_path=db_path,
    )
    insert_regulation(
        _sample_metadata(
            document_name="Wrong programme",
            applicable_batches=["2024"],
            applicable_programmes=["BSc AI"],
            verification_status="verified",
        ),
        db_path=db_path,
    )
    also_matching_id = insert_regulation(
        _sample_metadata(
            document_name="CS 2024 verified",
            regulation_version="v2",
            applicable_batches=["2024", "2025"],
            applicable_programmes=["BSc Computer Science"],
            verification_status="verified",
        ),
        db_path=db_path,
    )

    matches = get_applicable_regulations("2024", "BSc Computer Science", db_path=db_path)

    # Only administrator-verified/approved and applicability-matching records.
    assert [reg["id"] for reg in matches] == [matching_id, also_matching_id]
    assert all(
        reg["verification_status"] in {"approved", "verified"} for reg in matches
    )
    # No automatic latest-selection: all matching regulations are returned.
    assert [reg["regulation_version"] for reg in matches] == ["v1", "v2"]


def test_unverified_documents_excluded_from_applicable_regulations(tmp_path: Path) -> None:
    """Excludes unverified or non-approved documents from applicable evidence."""
    db_path = tmp_path / "cohortiq.db"
    init_database(db_path)

    insert_regulation(
        _sample_metadata(verification_status="unverified"),
        db_path=db_path,
    )
    insert_regulation(
        _sample_metadata(verification_status="pending_review"),
        db_path=db_path,
    )
    insert_regulation(
        _sample_metadata(verification_status=None),
        db_path=db_path,
    )

    matches = get_applicable_regulations("2024", "BSc Computer Science", db_path=db_path)

    assert matches == []


def test_delete_regulation_removes_metadata_and_pages(tmp_path: Path) -> None:
    """Deletes a regulation and its associated page records safely."""
    db_path = tmp_path / "cohortiq.db"
    init_database(db_path)
    regulation_id = insert_regulation(_sample_metadata(), db_path=db_path)
    insert_document_pages(
        regulation_id,
        [
            {"page_number": 1, "text": "Page 1", "status": "success"},
            {"page_number": 2, "text": "Page 2", "status": "success"},
        ],
        db_path=db_path,
    )

    deleted = delete_regulation(regulation_id, db_path=db_path)

    assert deleted is True
    assert get_regulation_by_id(regulation_id, db_path=db_path) is None
    assert get_document_pages(regulation_id, db_path=db_path) == []
    assert delete_regulation(regulation_id, db_path=db_path) is False


def test_foreign_key_relationship_enforced(tmp_path: Path) -> None:
    """Enforces foreign-key relationships for document pages."""
    db_path = tmp_path / "cohortiq.db"
    init_database(db_path)

    # get_connection enables PRAGMA foreign_keys = ON for DB operations.
    with pytest.raises(sqlite3.IntegrityError):
        insert_document_pages(
            9999,
            [{"page_number": 1, "text": "Orphan page", "status": "success"}],
            db_path=db_path,
        )


def test_page_insert_transaction_rolls_back_on_failure(tmp_path: Path) -> None:
    """Uses a transaction so failed multi-page inserts do not leave partial data."""
    db_path = tmp_path / "cohortiq.db"
    init_database(db_path)
    regulation_id = insert_regulation(_sample_metadata(), db_path=db_path)

    with pytest.raises((KeyError, TypeError, ValueError)):
        insert_document_pages(
            regulation_id,
            [
                {"page_number": 1, "text": "Valid page", "status": "success"},
                {"text": "Missing page number causes failure", "status": "success"},
            ],
            db_path=db_path,
        )

    assert get_document_pages(regulation_id, db_path=db_path) == []


def test_get_connection_enables_foreign_keys(tmp_path: Path) -> None:
    """Connection helper enables SQLite foreign-key enforcement."""
    db_path = tmp_path / "cohortiq.db"
    init_database(db_path)

    connection = get_connection(db_path)
    try:
        fk_status = connection.execute("PRAGMA foreign_keys;").fetchone()[0]
    finally:
        connection.close()

    assert fk_status == 1


def test_update_regulation_verification_status_explicitly_approves_unverified(
    tmp_path: Path,
) -> None:
    """Explicitly approves an unverified regulation without automatic approval."""
    db_path = tmp_path / "explicit_approval.db"
    init_database(db_path)
    regulation_id = insert_regulation(
        _sample_metadata(verification_status="unverified"),
        db_path=db_path,
    )

    # Upload/extraction/storage alone must not make it applicable (still unverified).
    assert get_applicable_regulations("2024", "BSc Computer Science", db_path=db_path) == []

    updated = update_regulation_verification_status(
        regulation_id, "approved", db_path=db_path
    )

    assert updated is True
    regulation = get_regulation_by_id(regulation_id, db_path=db_path)
    assert regulation is not None
    assert regulation["verification_status"] == "approved"
    matches = get_applicable_regulations("2024", "BSc Computer Science", db_path=db_path)
    assert [item["id"] for item in matches] == [regulation_id]


def test_update_regulation_verification_status_supports_rejection_and_pending(
    tmp_path: Path,
) -> None:
    """Supports explicit rejection/pending status updates via caller-supplied values."""
    db_path = tmp_path / "status_updates.db"
    init_database(db_path)
    regulation_id = insert_regulation(
        _sample_metadata(verification_status="unverified"),
        db_path=db_path,
    )

    assert update_regulation_verification_status(regulation_id, "pending", db_path=db_path) is True
    assert get_regulation_by_id(regulation_id, db_path=db_path)["verification_status"] == "pending"
    assert get_applicable_regulations("2024", "BSc Computer Science", db_path=db_path) == []

    assert update_regulation_verification_status(regulation_id, "rejected", db_path=db_path) is True
    assert get_regulation_by_id(regulation_id, db_path=db_path)["verification_status"] == "rejected"
    assert get_applicable_regulations("2024", "BSc Computer Science", db_path=db_path) == []


def test_update_regulation_verification_status_handles_nonexistent_regulation(
    tmp_path: Path,
) -> None:
    """Returns a clear failure result when the regulation ID does not exist."""
    db_path = tmp_path / "missing_regulation.db"
    init_database(db_path)

    updated = update_regulation_verification_status(9999, "approved", db_path=db_path)

    assert updated is False
    assert get_regulation_by_id(9999, db_path=db_path) is None


def test_unverified_regulations_remain_excluded_after_status_management(
    tmp_path: Path,
) -> None:
    """Keeps unverified/pending regulations excluded and preserves existing filtering."""
    db_path = tmp_path / "approval_safety.db"
    init_database(db_path)
    unverified_id = insert_regulation(
        _sample_metadata(
            document_name="Unverified Regulation",
            regulation_version="v1",
            verification_status="unverified",
        ),
        db_path=db_path,
    )
    approved_id = insert_regulation(
        _sample_metadata(
            document_name="Approved Regulation",
            regulation_version="v2",
            verification_status="administrator_verified",
        ),
        db_path=db_path,
    )

    assert update_regulation_verification_status(unverified_id, "pending", db_path=db_path) is True
    matches = get_applicable_regulations("2024", "BSc Computer Science", db_path=db_path)

    assert [item["id"] for item in matches] == [approved_id]
    assert get_regulation_by_id(unverified_id, db_path=db_path)["verification_status"] == "pending"
