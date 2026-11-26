"""Tests for FastAPI startup database initialization (lifespan).

Startup is exercised with ``with TestClient(app)``, which runs the application's
lifespan handler exactly as uvicorn does. The shared storage configuration is
redirected to a temporary directory for every test, and each test asserts that
the real project database file was not created, modified or deleted.
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from app.config import Settings
from app.database import (
    get_all_regulations,
    get_document_pages,
    init_database,
    insert_document_pages,
    insert_regulation,
)
from backend.app.main import app
from backend.tests.auth_support import sign_in_module_clients_as_administrator


@pytest.fixture(autouse=True)
def _signed_in_as_administrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoints exercised here require an administrator since Stage 4.

    Every client this module creates sends the token of a real administrator
    account created for the test (see ``backend/tests/auth_support.py``).
    """
    sign_in_module_clients_as_administrator(sys.modules[__name__], app, tmp_path, monkeypatch)


API = "/api/v1"
REQUIRED_TABLES = {"regulations", "document_pages"}


def _file_signature(path: Path) -> tuple[int, int] | None:
    """Return (size, mtime_ns) for a file, or None when it does not exist."""
    if not path.exists():
        return None
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns)


def _table_names(db_path: Path) -> set[str]:
    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Point FastAPI startup and the database layer at isolated temporary storage."""
    real_db_path = Path(app_config.get_settings().database_path).resolve()
    real_db_before = _file_signature(real_db_path)

    isolated = Settings(
        gemini_api_key=None,
        database_path=tmp_path / "fresh_data" / "cohortiq.db",
        upload_dir=tmp_path / "fresh_data" / "uploads",
        extracted_dir=tmp_path / "fresh_data" / "extracted",
    )
    # Startup resolves configuration through this name in backend.app.main;
    # API routes fall back to the database layer's configured default path.
    monkeypatch.setattr("backend.app.main.get_storage_settings", lambda: isolated)
    monkeypatch.setattr("app.database.get_settings", lambda: isolated)

    yield isolated

    assert _file_signature(real_db_path) == real_db_before, "The real project database changed."


def test_startup_creates_fresh_database_with_required_tables(storage: Settings) -> None:
    db_path = Path(storage.database_path)
    assert not db_path.exists()
    assert not db_path.parent.exists()

    with TestClient(app) as client:
        assert db_path.is_file()
        assert REQUIRED_TABLES <= _table_names(db_path)
        assert Path(storage.upload_dir).is_dir()
        assert Path(storage.extracted_dir).is_dir()
        assert client.app.state.database_path == db_path


def test_required_table_columns_match_database_layer(storage: Settings) -> None:
    with TestClient(app):
        pass

    with closing(sqlite3.connect(storage.database_path)) as connection:
        regulation_columns = {row[1] for row in connection.execute("PRAGMA table_info(regulations)")}
        page_columns = {row[1] for row in connection.execute("PRAGMA table_info(document_pages)")}

    assert {
        "id",
        "document_name",
        "regulation_version",
        "effective_date",
        "applicable_batches",
        "applicable_programmes",
        "upload_date",
        "total_pages",
        "processing_status",
        "verification_status",
    } <= regulation_columns
    assert {"id", "regulation_id", "page_number", "extracted_text", "extraction_status"} <= page_columns


def test_read_endpoints_work_on_fresh_database(storage: Settings) -> None:
    """No dependency overrides: routes use the configured database initialized at startup."""
    with TestClient(app) as client:
        regulations = client.get(f"{API}/regulations")
        assert regulations.status_code == 200
        assert regulations.json() == {"regulations": []}

        assert client.get(f"{API}/regulations/1").status_code == 404
        assert client.get(f"{API}/regulations/1/pages").status_code == 404

        cohort = client.get(f"{API}/cohorts/2024/BSc%20CS/regulations")
        assert cohort.status_code == 200
        assert cohort.json() == {"regulations": []}

        assert client.get(f"{API}/health").json()["status"] == "ok"


def test_startup_preserves_existing_records(storage: Settings) -> None:
    db_path = Path(storage.database_path)
    init_database(db_path)
    regulation_id = insert_regulation(
        {
            "document_name": "Existing Regulation",
            "regulation_version": "R2023",
            "effective_date": "2023-07-01",
            "applicable_batches": ["2023"],
            "applicable_programmes": ["BSc CS"],
            "upload_date": "2023-06-15",
            "total_pages": 1,
            "processing_status": "extracted",
            "verification_status": "approved",
        },
        db_path=db_path,
    )
    insert_document_pages(
        regulation_id,
        [{"page_number": 1, "extracted_text": "Attendance must be 75 percent.", "extraction_status": "success"}],
        db_path=db_path,
    )
    regulations_before = get_all_regulations(db_path)
    pages_before = get_document_pages(regulation_id, db_path)

    # Start the application twice to simulate a restart.
    for _ in range(2):
        with TestClient(app) as client:
            response = client.get(f"{API}/regulations")
            assert response.status_code == 200
            assert [item["id"] for item in response.json()["regulations"]] == [regulation_id]

            pages = client.get(f"{API}/regulations/{regulation_id}/pages").json()["pages"]
            assert pages[0]["extracted_text"] == "Attendance must be 75 percent."

            cohort = client.get(f"{API}/cohorts/2023/BSc%20CS/regulations").json()["regulations"]
            assert [item["id"] for item in cohort] == [regulation_id]

    assert get_all_regulations(db_path) == regulations_before
    assert get_document_pages(regulation_id, db_path) == pages_before


def test_startup_failure_is_raised_and_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An unusable database path stops startup with a clear error instead of being ignored."""
    unusable_db_path = tmp_path / "database_path_is_a_directory"
    unusable_db_path.mkdir()
    broken = Settings(
        gemini_api_key=None,
        database_path=unusable_db_path,
        upload_dir=tmp_path / "uploads",
        extracted_dir=tmp_path / "extracted",
    )
    monkeypatch.setattr("backend.app.main.get_storage_settings", lambda: broken)
    monkeypatch.setattr("app.database.get_settings", lambda: broken)

    with caplog.at_level("ERROR", logger="backend.app.main"):
        with pytest.raises(RuntimeError, match="Failed to initialize the CohortIQ AI database") as excinfo:
            with TestClient(app):
                pass  # pragma: no cover - startup must fail before reaching here

    assert isinstance(excinfo.value.__cause__, sqlite3.Error)
    assert "database initialization error" in caplog.text
