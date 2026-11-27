from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import init_database, insert_regulation_with_pages, update_regulation_verification_status
from backend.app.api import deps
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.main import app
from backend.app.services.change_radar import init_change_radar_tables
from backend.tests.auth_support import (
    create_signed_in_account,
    make_auth_settings,
    use_auth_database,
)


@pytest.fixture
def radar_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "radar.db"
    init_database(database_path)
    init_change_radar_tables(database_path)
    settings = make_auth_settings()
    use_auth_database(app, monkeypatch, database_path, settings)
    monkeypatch.setitem(app.dependency_overrides, regulation_routes.get_db_path, lambda: str(database_path))
    admin = create_signed_in_account(database_path, settings, "administrator")
    student = create_signed_in_account(
        database_path, settings, "student", admission_batch="2024", programme="BTech CS"
    )
    other_student = create_signed_in_account(
        database_path, settings, "student", admission_batch="2025", programme="BTech CS"
    )
    staff = create_signed_in_account(database_path, settings, "staff", admission_batch="2024", programme="BTech CS")
    old_id = insert_regulation_with_pages(
        {
            "document_name": "Academic Regulation",
            "regulation_version": "2023",
            "applicable_batches": ["2024"],
            "applicable_programmes": ["BTech CS"],
            "upload_date": "2025-01-01",
            "verification_status": "approved",
        },
        [{"page_number": 12, "text": "5.1 Attendance must be at least 75 percent."}],
        database_path,
    )
    new_id = insert_regulation_with_pages(
        {
            "document_name": "Academic Regulation",
            "regulation_version": "2024",
            "applicable_batches": ["2024", "2025"],
            "applicable_programmes": ["BTech CS"],
            "upload_date": "2025-02-01",
            "verification_status": "pending",
        },
        [
            {"page_number": 14, "text": "5.1 Attendance must be at least 80 percent."},
            {"page_number": 15, "text": "5.2 Students must follow the examination schedule."},
        ],
        database_path,
    )
    client = TestClient(app)
    yield client, database_path, admin, student, other_student, staff, old_id, new_id
    app.dependency_overrides.pop(deps.get_auth_db_path, None)
    app.dependency_overrides.pop(regulation_routes.get_db_path, None)


def test_admin_comparison_review_and_cohort_gated_student_visibility(radar_env):
    client, database_path, admin, student, other_student, staff, old_id, new_id = radar_env
    create_response = client.post(
        "/api/v1/change-radar/reviews",
        headers=admin.headers,
        json={
            "previous_regulation_id": old_id,
            "new_regulation_id": new_id,
            "applicable_batches": ["2024"],
            "applicable_programmes": ["BTech CS"],
        },
    )
    assert create_response.status_code == 201
    review = create_response.json()
    assert review["status"] == "needs_review"
    assert review["warning"] == "Potential changes — review required."
    assert {item["change_type"] for item in review["changes"]} == {"modification", "addition"}
    assert review["changes"][0]["previous_page"] == 12
    assert review["changes"][0]["new_page"] == 14
    from backend.app.audit.repository import list_audit_events

    audit = list_audit_events(action="regulation.change_reviewed", db_path=database_path)
    assert audit.total == 1

    assert client.get("/api/v1/change-radar/reviews", headers=student.headers).status_code == 403
    assert client.get("/api/v1/change-radar/reviews", headers=staff.headers).status_code == 403
    assert client.get("/api/v1/updates", headers=student.headers).json() == {"updates": []}
    assert len(client.get("/api/v1/updates", headers=staff.headers).json()["updates"]) == 0

    approved_review = client.patch(
        f"/api/v1/change-radar/reviews/{review['id']}",
        headers=admin.headers,
        json={"status": "approved"},
    )
    assert approved_review.status_code == 200
    assert client.get("/api/v1/updates", headers=student.headers).json() == {"updates": []}

    assert update_regulation_verification_status(new_id, "approved", database_path)
    student_updates = client.get("/api/v1/updates", headers=student.headers)
    assert student_updates.status_code == 200
    assert len(student_updates.json()["updates"]) == 1
    assert len(client.get("/api/v1/updates", headers=staff.headers).json()["updates"]) == 1
    assert client.get("/api/v1/updates", headers=other_student.headers).json() == {"updates": []}


def test_comparison_rejects_non_applicable_cohort_and_students_cannot_create(radar_env):
    client, _database_path, admin, student, _other_student, _staff, old_id, new_id = radar_env
    payload = {
        "previous_regulation_id": old_id,
        "new_regulation_id": new_id,
        "applicable_batches": ["2026"],
        "applicable_programmes": ["BTech CS"],
    }
    assert client.post("/api/v1/change-radar/reviews", headers=admin.headers, json=payload).status_code == 422
    payload["applicable_batches"] = ["2024"]
    assert client.post("/api/v1/change-radar/reviews", headers=student.headers, json=payload).status_code == 403
