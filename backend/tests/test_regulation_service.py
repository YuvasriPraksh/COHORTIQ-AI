"""Tests for the backend regulation service delegation layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import sentinel

from pytest import MonkeyPatch

from backend.app.services import regulation_service


def test_ingest_regulation_delegates_to_workflow(monkeypatch: MonkeyPatch) -> None:
    """Ingestion service should delegate to app.workflow with preserved args/return."""
    calls: dict[str, object] = {}

    def fake_ingest_uploaded_regulation(*, pdf_path, metadata, db_path):
        calls["pdf_path"] = pdf_path
        calls["metadata"] = metadata
        calls["db_path"] = db_path
        return {"status": "ingested", "result": sentinel.ingest}

    monkeypatch.setattr(
        "app.workflow.ingest_uploaded_regulation",
        fake_ingest_uploaded_regulation,
    )

    metadata = {"document_name": "Reg A"}
    pdf_path = Path("C:/tmp/regulation.pdf")
    result = regulation_service.ingest_regulation(
        pdf_path=pdf_path,
        metadata=metadata,
        db_path="C:/tmp/test.db",
    )

    assert result == {"status": "ingested", "result": sentinel.ingest}
    assert calls == {
        "pdf_path": pdf_path,
        "metadata": metadata,
        "db_path": "C:/tmp/test.db",
    }


def test_approve_or_verify_regulation_delegates_to_workflow(
    monkeypatch: MonkeyPatch,
) -> None:
    """Approval/verification service should delegate to app.workflow explicitly."""
    calls: dict[str, object] = {}

    def fake_approve_regulation(*, regulation_id, db_path, verification_status):
        calls["regulation_id"] = regulation_id
        calls["db_path"] = db_path
        calls["verification_status"] = verification_status
        return {"status": "updated", "result": sentinel.approve}

    monkeypatch.setattr("app.workflow.approve_regulation", fake_approve_regulation)

    result = regulation_service.approve_or_verify_regulation(
        regulation_id=42,
        db_path="C:/tmp/test.db",
        verification_status="approved",
    )

    assert result == {"status": "updated", "result": sentinel.approve}
    assert calls == {
        "regulation_id": 42,
        "db_path": "C:/tmp/test.db",
        "verification_status": "approved",
    }


def test_list_regulations_delegates_to_database(monkeypatch: MonkeyPatch) -> None:
    """Listing service should delegate to app.database and preserve return value."""
    calls: dict[str, object] = {}

    def fake_get_all_regulations(*, db_path):
        calls["db_path"] = db_path
        return [{"id": 1, "document_name": "Reg A"}]

    monkeypatch.setattr("app.database.get_all_regulations", fake_get_all_regulations)

    result = regulation_service.list_regulations(db_path="C:/tmp/test.db")

    assert result == [{"id": 1, "document_name": "Reg A"}]
    assert calls == {"db_path": "C:/tmp/test.db"}


def test_get_regulation_details_delegates_to_database(
    monkeypatch: MonkeyPatch,
) -> None:
    """Details service should delegate to app.database with preserved args/return."""
    calls: dict[str, object] = {}

    def fake_get_regulation_by_id(*, regulation_id, db_path):
        calls["regulation_id"] = regulation_id
        calls["db_path"] = db_path
        return {"id": regulation_id, "document_name": "Reg A"}

    monkeypatch.setattr("app.database.get_regulation_by_id", fake_get_regulation_by_id)

    result = regulation_service.get_regulation_details(
        regulation_id=7, db_path="C:/tmp/test.db"
    )

    assert result == {"id": 7, "document_name": "Reg A"}
    assert calls == {"regulation_id": 7, "db_path": "C:/tmp/test.db"}


def test_get_regulation_document_pages_delegates_to_database(
    monkeypatch: MonkeyPatch,
) -> None:
    """Pages service should delegate to app.database with preserved args/return."""
    calls: dict[str, object] = {}

    def fake_get_document_pages(*, regulation_id, db_path):
        calls["regulation_id"] = regulation_id
        calls["db_path"] = db_path
        return [{"page_number": 1, "extracted_text": "text"}]

    monkeypatch.setattr("app.database.get_document_pages", fake_get_document_pages)

    result = regulation_service.get_regulation_document_pages(
        regulation_id=7, db_path="C:/tmp/test.db"
    )

    assert result == [{"page_number": 1, "extracted_text": "text"}]
    assert calls == {"regulation_id": 7, "db_path": "C:/tmp/test.db"}
