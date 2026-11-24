"""Atomic PDF ingestion: the regulation row and all page rows commit together or not at all.

Rollback is proven with a real SQLite failure rather than a mock: a regular
``BEFORE INSERT`` trigger on ``document_pages`` aborts when ``page_number = 3``.
By then the regulation row and pages 1-2 have already been written inside the
same transaction, so the test shows they are all rolled back.

(A ``CREATE TEMP TRIGGER`` would not work here: temp triggers exist only on the
connection that created them, and the code under test opens its own connection.)

Every test uses an isolated temporary SQLite database; the real project database
is never touched and Gemini is never called.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterator

import fitz
import pytest
from fastapi.testclient import TestClient

from app import database, workflow
from app.database import (
    get_document_pages,
    get_regulation_by_id,
    init_database,
    insert_document_pages,
    insert_regulation,
    insert_regulation_with_pages,
)
from backend.app.api.v1 import query as query_routes
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.main import app
from backend.app.services import regulation_service

TRIGGER_NAME = "fail_on_page_three"
TRIGGER_MESSAGE = "simulated page insert failure"
PAGE_COUNT = 5
WORKFLOW_LOGGER = "app.workflow"

METADATA: dict[str, Any] = {
    "document_name": "R2024 Academic Regulations",
    "regulation_version": "R2024",
    "effective_date": "2024-08-01",
    "applicable_batches": ["2024", "2025"],
    "applicable_programmes": ["BSc CS"],
    "upload_date": "2024-07-15",
    "total_pages": PAGE_COUNT,
    "processing_status": "extracted",
    "verification_status": "pending",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "atomic_ingestion.db"
    init_database(path)
    return path


def _pages(count: int = PAGE_COUNT) -> list[dict[str, Any]]:
    """Page records in the shape produced by the PDF processor."""
    return [
        {"page_number": number, "text": f"Clause {number}: rule text for page {number}.", "status": "success"}
        for number in range(1, count + 1)
    ]


def _counts(db_path: Path) -> tuple[int, int]:
    with closing(sqlite3.connect(db_path)) as connection:
        regulations = connection.execute("SELECT COUNT(*) FROM regulations").fetchone()[0]
        pages = connection.execute("SELECT COUNT(*) FROM document_pages").fetchone()[0]
    return regulations, pages


def _snapshot(db_path: Path) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    with closing(sqlite3.connect(db_path)) as connection:
        regulations = connection.execute("SELECT * FROM regulations ORDER BY id").fetchall()
        pages = connection.execute("SELECT * FROM document_pages ORDER BY id").fetchall()
    return regulations, pages


def _add_failing_trigger(db_path: Path, page_number: int = 3) -> None:
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            f"""
            CREATE TRIGGER {TRIGGER_NAME}
            BEFORE INSERT ON document_pages
            WHEN NEW.page_number = {int(page_number)}
            BEGIN
                SELECT RAISE(ABORT, '{TRIGGER_MESSAGE}');
            END;
            """
        )
        connection.commit()


def _drop_failing_trigger(db_path: Path) -> None:
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(f"DROP TRIGGER IF EXISTS {TRIGGER_NAME};")
        connection.commit()


def _write_pdf(directory: Path, page_count: int = PAGE_COUNT) -> Path:
    pdf_path = directory / "regulation.pdf"
    document = fitz.open()
    try:
        for number in range(1, page_count + 1):
            document.new_page().insert_text((72, 72), f"Clause {number}: attendance rule text.")
        document.save(pdf_path)
    finally:
        document.close()
    return pdf_path


def _workflow_metadata() -> dict[str, Any]:
    return {
        key: METADATA[key]
        for key in ("document_name", "regulation_version", "effective_date", "applicable_batches", "applicable_programmes")
    }


# --------------------------------------------------------------------------- #
# A. Successful combined insertion
# --------------------------------------------------------------------------- #


def test_combined_insert_saves_regulation_and_all_pages(db_path: Path) -> None:
    regulation_id = insert_regulation_with_pages(METADATA, _pages(), db_path=db_path)

    regulation = get_regulation_by_id(regulation_id, db_path=db_path)
    assert regulation is not None
    assert regulation["document_name"] == METADATA["document_name"]
    assert regulation["applicable_batches"] == ["2024", "2025"]
    assert regulation["verification_status"] == "pending"

    pages = get_document_pages(regulation_id, db_path=db_path)
    assert [page["page_number"] for page in pages] == list(range(1, PAGE_COUNT + 1))
    assert all(page["extraction_status"] == "success" for page in pages)
    assert pages[2]["extracted_text"] == "Clause 3: rule text for page 3."
    assert _counts(db_path) == (1, PAGE_COUNT)


def test_combined_insert_stores_identical_rows_to_legacy_helpers(tmp_path: Path) -> None:
    """The refactor must not change validation or normalization."""
    combined_db = tmp_path / "combined.db"
    legacy_db = tmp_path / "legacy.db"
    init_database(combined_db)
    init_database(legacy_db)

    insert_regulation_with_pages(METADATA, _pages(), db_path=combined_db)
    legacy_id = insert_regulation(METADATA, db_path=legacy_db)
    insert_document_pages(legacy_id, _pages(), db_path=legacy_db)

    assert _snapshot(combined_db) == _snapshot(legacy_db)


# --------------------------------------------------------------------------- #
# B/C. Real SQLite failure mid-transaction rolls back everything
# --------------------------------------------------------------------------- #


def test_sqlite_trigger_failure_rolls_back_regulation_and_pages(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_failing_trigger(db_path, page_number=3)

    # Record the SQL executed on the connection used by the insert.
    statements: list[str] = []
    real_get_connection = database.get_connection

    def tracing_get_connection(path: Any = None) -> sqlite3.Connection:
        connection = real_get_connection(path)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(database, "get_connection", tracing_get_connection)

    with pytest.raises(sqlite3.DatabaseError, match=TRIGGER_MESSAGE):
        insert_regulation_with_pages(METADATA, _pages(), db_path=db_path)

    # C. Nothing persisted: both tables are empty.
    assert _counts(db_path) == (0, 0)

    # The regulation row was written inside the transaction before the failure,
    # and the transaction ended in ROLLBACK, never COMMIT.
    executed = " ".join(statement.upper() for statement in statements)
    assert "BEGIN" in executed
    assert "INSERT INTO REGULATIONS" in executed
    assert "INSERT INTO DOCUMENT_PAGES" in executed
    assert "ROLLBACK" in executed
    assert "COMMIT" not in executed


def test_failure_on_first_or_last_page_also_rolls_back(db_path: Path) -> None:
    for failing_page in (1, PAGE_COUNT):
        _add_failing_trigger(db_path, page_number=failing_page)
        with pytest.raises(sqlite3.DatabaseError, match=TRIGGER_MESSAGE):
            insert_regulation_with_pages(METADATA, _pages(), db_path=db_path)
        _drop_failing_trigger(db_path)
        assert _counts(db_path) == (0, 0)


def test_interrupt_during_insert_also_rolls_back(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rollback covers non-Exception interrupts too (e.g. KeyboardInterrupt)."""

    def interrupted(*_args: Any, **_kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(database, "_insert_page_rows", interrupted)

    with pytest.raises(KeyboardInterrupt):
        insert_regulation_with_pages(METADATA, _pages(), db_path=db_path)

    assert _counts(db_path) == (0, 0)


# --------------------------------------------------------------------------- #
# D. Pre-existing records remain unchanged
# --------------------------------------------------------------------------- #


def test_failed_insert_leaves_existing_records_unchanged(db_path: Path) -> None:
    existing_id = insert_regulation_with_pages(
        {**METADATA, "document_name": "Existing Regulation", "verification_status": "approved"},
        _pages(2),
        db_path=db_path,
    )
    before = _snapshot(db_path)

    _add_failing_trigger(db_path, page_number=3)
    with pytest.raises(sqlite3.DatabaseError):
        insert_regulation_with_pages(METADATA, _pages(), db_path=db_path)

    assert _snapshot(db_path) == before
    assert _counts(db_path) == (1, 2)
    assert get_regulation_by_id(existing_id, db_path=db_path)["verification_status"] == "approved"


# --------------------------------------------------------------------------- #
# E. Invalid input saves nothing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("bad_page", "error"),
    [
        pytest.param({"page_number": "three", "text": "x"}, ValueError, id="non_numeric_page_number"),
        pytest.param({"text": "missing page number"}, KeyError, id="missing_page_number"),
        pytest.param({"page_number": None, "text": "x"}, TypeError, id="null_page_number"),
    ],
)
def test_invalid_page_data_saves_nothing(db_path: Path, bad_page: dict[str, Any], error: type) -> None:
    insert_regulation_with_pages({**METADATA, "document_name": "Existing"}, _pages(1), db_path=db_path)
    before = _snapshot(db_path)
    pages = _pages(2) + [bad_page] + _pages(5)[3:]

    with pytest.raises(error):
        insert_regulation_with_pages(METADATA, pages, db_path=db_path)

    assert _snapshot(db_path) == before


def test_invalid_metadata_saves_nothing_and_does_not_create_database(tmp_path: Path) -> None:
    missing_db = tmp_path / "not_created" / "cohortiq.db"
    incomplete = {key: value for key, value in METADATA.items() if key != "upload_date"}

    with pytest.raises(KeyError, match="upload_date"):
        insert_regulation_with_pages(incomplete, _pages(), db_path=missing_db)
    with pytest.raises(KeyError, match="upload_date"):
        insert_regulation(incomplete, db_path=missing_db)

    # Validation happens before any connection is opened (unchanged behaviour).
    assert not missing_db.parent.exists()


# --------------------------------------------------------------------------- #
# F/G. Workflow-level failure
# --------------------------------------------------------------------------- #


def test_workflow_storage_failure_returns_error_without_regulation_id(
    db_path: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _add_failing_trigger(db_path, page_number=3)
    pdf_path = _write_pdf(tmp_path)

    with caplog.at_level(logging.ERROR, logger=WORKFLOW_LOGGER):
        result = workflow.ingest_uploaded_regulation(pdf_path, _workflow_metadata(), db_path=db_path)

    # F. Safe failure result; nothing persisted.
    assert result["status"] == "error"
    assert result["regulation_id"] is None
    assert result["message"].startswith("Failed to store regulation data:")
    assert result["extraction_summary"]["total_pages"] == PAGE_COUNT
    assert _counts(db_path) == (0, 0)

    # G. The original exception is logged with its traceback.
    records = [record for record in caplog.records if record.name == WORKFLOW_LOGGER]
    assert len(records) == 1
    assert records[0].exc_info is not None
    assert isinstance(records[0].exc_info[1], sqlite3.DatabaseError)
    assert TRIGGER_MESSAGE in caplog.text
    assert "Traceback" in caplog.text
    assert "rolled back" in records[0].getMessage()

    # The API classifier still recognizes this as an internal (500) failure.
    assert (
        regulation_service.classify_ingestion_failure(result)
        is regulation_service.IngestionFailureKind.INTERNAL_ERROR
    )


def test_workflow_success_result_is_unchanged(db_path: Path, tmp_path: Path) -> None:
    result = workflow.ingest_uploaded_regulation(_write_pdf(tmp_path), _workflow_metadata(), db_path=db_path)

    assert set(result) == {"status", "regulation_id", "verification_status", "extraction_summary", "message"}
    assert result["status"] == "ingested"
    assert result["verification_status"] == "pending"
    assert result["message"] == "Regulation ingested and stored as pending administrator verification."
    assert isinstance(result["regulation_id"], int)
    assert _counts(db_path) == (1, PAGE_COUNT)


# --------------------------------------------------------------------------- #
# H/I/J/K. API-level behaviour
# --------------------------------------------------------------------------- #


class ApiEnv:
    def __init__(self, client: TestClient, db_path: Path, tmp_path: Path, temp_paths: list[Path]) -> None:
        self.client = client
        self.db_path = db_path
        self.tmp_path = tmp_path
        self.temp_paths = temp_paths

    def upload(self) -> Any:
        pdf_bytes = _write_pdf(self.tmp_path).read_bytes()
        return self.client.post(
            "/api/v1/regulations/ingest",
            data={
                "document_name": METADATA["document_name"],
                "regulation_version": METADATA["regulation_version"],
                "effective_date": METADATA["effective_date"],
                "applicable_batches": METADATA["applicable_batches"],
                "applicable_programmes": METADATA["applicable_programmes"],
            },
            files={"file": ("regulation.pdf", pdf_bytes, "application/pdf")},
        )


@pytest.fixture
def api(db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ApiEnv]:
    temp_paths: list[Path] = []
    real_ingest = regulation_service.ingest_regulation

    def recording_ingest(pdf_path: Any, metadata: Any, db_path: Any = None) -> dict[str, Any]:
        temp_paths.append(Path(pdf_path))
        return real_ingest(pdf_path=pdf_path, metadata=metadata, db_path=db_path)

    monkeypatch.setattr(regulation_service, "ingest_regulation", recording_ingest)
    app.dependency_overrides[regulation_routes.get_db_path] = lambda: str(db_path)
    app.dependency_overrides[query_routes.get_db_path] = lambda: str(db_path)
    try:
        yield ApiEnv(TestClient(app), db_path, tmp_path, temp_paths)
    finally:
        app.dependency_overrides.pop(regulation_routes.get_db_path, None)
        app.dependency_overrides.pop(query_routes.get_db_path, None)


def _assert_safe_ingestion_500(response: Any, *forbidden: str) -> None:
    assert response.status_code == 500
    assert response.json() == {"detail": regulation_routes.INGESTION_INTERNAL_ERROR_DETAIL}
    for marker in (TRIGGER_MESSAGE, "IntegrityError", "Traceback", "Failed to store", *forbidden):
        assert marker not in response.text, f"Response leaked {marker!r}"


def test_api_storage_failure_returns_safe_500_and_saves_nothing(api: ApiEnv) -> None:
    _add_failing_trigger(api.db_path, page_number=3)

    response = api.upload()

    # H. Generic 500 with no internal details; nothing stored.
    _assert_safe_ingestion_500(response, str(api.db_path), str(api.tmp_path))
    assert api.client.get("/api/v1/regulations").json() == {"regulations": []}
    assert _counts(api.db_path) == (0, 0)

    # I. The temporary upload file was removed.
    assert len(api.temp_paths) == 1
    assert not api.temp_paths[0].exists()


def test_api_retry_after_dropping_trigger_saves_all_pages(api: ApiEnv) -> None:
    _add_failing_trigger(api.db_path, page_number=3)
    assert api.upload().status_code == 500

    # J. Once the fault is gone, the same upload succeeds completely.
    _drop_failing_trigger(api.db_path)
    response = api.upload()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ingested"
    assert body["verification_status"] == "pending"
    assert body["extraction_summary"]["total_pages"] == PAGE_COUNT

    pages = api.client.get(f"/api/v1/regulations/{body['regulation_id']}/pages").json()["pages"]
    assert [page["page_number"] for page in pages] == list(range(1, PAGE_COUNT + 1))
    assert _counts(api.db_path) == (1, PAGE_COUNT)
    assert all(not path.exists() for path in api.temp_paths)


def test_api_unusable_database_returns_safe_500(api: ApiEnv) -> None:
    # K. The configured database path is a directory, so SQLite cannot open it.
    unusable = api.tmp_path / "database_path_is_a_directory"
    unusable.mkdir()
    app.dependency_overrides[regulation_routes.get_db_path] = lambda: str(unusable)

    response = api.upload()

    _assert_safe_ingestion_500(response, str(unusable), "unable to open")
    assert list(unusable.iterdir()) == []
    assert all(not path.exists() for path in api.temp_paths)
