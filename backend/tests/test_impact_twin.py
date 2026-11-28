from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import init_database, insert_regulation_with_pages, update_regulation_verification_status
from backend.app.api import deps
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.main import app
from backend.app.services.change_radar import init_change_radar_tables
from backend.app.services.impact_twin import (
    NO_DIRECT_IMPACT,
    POTENTIAL_IMPACT,
    REQUIRES_REVIEW,
    classify_change,
)
from backend.tests.auth_support import create_signed_in_account, make_auth_settings, use_auth_database


# ---------------------------------------------------------------------------
# Classification rules (deterministic, from clause text only)
# ---------------------------------------------------------------------------


def _mod(previous: str, new: str) -> dict:
    return {"change_type": "modification", "previous_text": previous, "new_text": new}


def test_numeric_change_is_potential_impact_and_lists_values():
    result = classify_change(_mod("5.1 Attendance must be at least 75 percent.", "5.1 Attendance must be at least 80 percent."))
    assert result["classification"] == POTENTIAL_IMPACT
    assert result["previous_values"] == ["75%"]
    assert result["revised_values"] == ["80%"]
    assert "attendance" in result["topics"]


def test_clause_number_alone_is_not_treated_as_a_value_change():
    result = classify_change(_mod("5.1 Students shall attend all classes.", "6.1 Students shall attend all classes."))
    assert result["classification"] == NO_DIRECT_IMPACT
    assert result["previous_values"] == [] and result["revised_values"] == []


def test_edition_years_and_page_numbers_in_headers_are_not_value_changes():
    result = classify_change(
        {
            "change_type": "modification",
            "previous_page": 7,
            "new_page": 7,
            "previous_text": "Academic Regulations 2020 (R-2020) 7 CAM : Continuous Assessment Marks ESE : End Semester Examination",
            "new_text": "Academic Regulations 2023 (R-2023) 7 CAM : Continuous Assessment Marks ESE : End Semester Examination",
        }
    )
    assert result["previous_values"] == [] and result["revised_values"] == []
    assert result["classification"] != POTENTIAL_IMPACT


def test_clause_cross_references_are_not_values_but_cgpa_thresholds_are():
    refs = classify_change(_mod("Students stopped under Regulation 10.2 must rejoin.", "Students stopped under Regulation 10.3 must rejoin."))
    assert refs["previous_values"] == [] and refs["revised_values"] == []
    cgpa = classify_change(_mod("A CGPA of not less than 8.0 is required for honours.", "A CGPA of not less than 7.5 is required for honours."))
    assert cgpa["classification"] == POTENTIAL_IMPACT
    assert (cgpa["previous_values"], cgpa["revised_values"]) == (["8.0"], ["7.5"])


def test_unrelated_paired_passages_require_review_even_if_numbers_differ():
    result = classify_change(
        _mod(
            "After registering for all the courses, the student must attend 90 hours of classes.",
            "The process and guidelines for in-house projects require 3 reviews with the HoD.",
        )
    )
    assert result["classification"] == REQUIRES_REVIEW


def test_table_of_contents_and_academic_year_suffixes_are_not_values():
    toc = classify_change(_mod("1. Introduction ........... 5 2. Definitions ........... 9", "1. Introduction ........... 6 2. Definitions ........... 8"))
    assert toc["previous_values"] == [] and toc["revised_values"] == []
    year = classify_change(_mod("With effect from academic year 2020-21 onwards", "With effect from academic year 2023-24 onwards"))
    assert year["previous_values"] == [] and year["revised_values"] == []


def test_minor_wording_with_same_numbers_has_no_direct_impact():
    result = classify_change(
        _mod(
            "Students must secure a minimum of 75% attendance in each course to be eligible for the end semester examination.",
            "Students must secure a minimum of 75% attendance in every course to be eligible for the end semester examination.",
        )
    )
    assert result["classification"] == NO_DIRECT_IMPACT


def test_additions_removals_and_substantial_rewording_require_review():
    assert classify_change({"change_type": "addition", "previous_text": None, "new_text": "5.2 New rule."})["classification"] == REQUIRES_REVIEW
    assert classify_change({"change_type": "removal", "previous_text": "5.2 Old rule.", "new_text": None})["classification"] == REQUIRES_REVIEW
    reworded = classify_change(_mod("Re-registration is permitted once per course.", "A course may be repeated only with permission of the Dean."))
    assert reworded["classification"] == REQUIRES_REVIEW


# ---------------------------------------------------------------------------
# API: approval-gated, cohort-scoped visibility
# ---------------------------------------------------------------------------


@pytest.fixture
def twin_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "twin.db"
    init_database(database_path)
    init_change_radar_tables(database_path)
    settings = make_auth_settings()
    use_auth_database(app, monkeypatch, database_path, settings)
    monkeypatch.setitem(app.dependency_overrides, regulation_routes.get_db_path, lambda: str(database_path))
    admin = create_signed_in_account(database_path, settings, "administrator")
    student = create_signed_in_account(database_path, settings, "student", admission_batch="2024", programme="BTech CS")
    other_student = create_signed_in_account(database_path, settings, "student", admission_batch="2025", programme="BTech CS")
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


def _twin(client: TestClient, account, params: str = "") -> dict:
    response = client.get(f"/api/v1/impact-twin{params}", headers=account.headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_impact_twin_shows_only_approved_applicable_changes_with_evidence(twin_env):
    client, database_path, admin, student, other_student, staff, old_id, new_id = twin_env

    before = _twin(client, student)
    assert before["cohort"] == {"admission_batch": "2024", "programme": "BTech CS"}
    assert [reg["id"] for reg in before["applicable_regulations"]] == [old_id]
    assert before["assessments"] == [] and before["latest_update"] is None
    assert before["summary"]["total"] == 0
    assert before["personal_records_available"] is False

    review = client.post(
        "/api/v1/change-radar/reviews",
        headers=admin.headers,
        json={"previous_regulation_id": old_id, "new_regulation_id": new_id, "applicable_batches": ["2024"], "applicable_programmes": ["BTech CS"]},
    ).json()
    # Detected but not reviewed: hidden.
    assert _twin(client, student)["assessments"] == []

    assert client.patch(f"/api/v1/change-radar/reviews/{review['id']}", headers=admin.headers, json={"status": "approved"}).status_code == 200
    # Review approved but the new regulation itself is still pending: hidden.
    assert _twin(client, student)["assessments"] == []

    assert update_regulation_verification_status(new_id, "approved", database_path)
    result = _twin(client, student)
    assert result["summary"] == {"potential_impact": 1, "requires_review": 1, "no_direct_impact": 0, "total": 2}
    assert result["latest_update"]["review_id"] == review["id"]
    assert result["latest_update"]["new_version"] == "2024"

    first, second = result["assessments"]
    assert first["classification"] == "potential_impact"
    assert first["classification_label"] == "Potential Impact"
    assert first["clause"] == "5.1"
    assert first["previous_text"] == "5.1 Attendance must be at least 75 percent."
    assert first["new_text"] == "5.1 Attendance must be at least 80 percent."
    assert (first["previous_page"], first["new_page"]) == (12, 14)
    assert (first["previous_version"], first["new_version"]) == ("2023", "2024")
    assert first["previous_values"] == ["75%"] and first["revised_values"] == ["80%"]
    assert any("page 14" in point for point in first["review_points"])
    assert any("page 12" in point for point in first["review_points"])
    assert second["classification"] == "requires_review" and second["change_type"] == "addition"
    assert second["new_page"] == 15 and second["previous_page"] is None

    # Staff with the same assigned cohort see it; another cohort does not.
    assert _twin(client, staff)["summary"]["total"] == 2
    assert _twin(client, other_student)["assessments"] == []
    # A client-supplied cohort is ignored: the account's cohort is always used.
    spoofed = _twin(client, other_student, "?admission_batch=2024&programme=BTech%20CS")
    assert spoofed["cohort"]["admission_batch"] == "2025" and spoofed["assessments"] == []

    # Returning the review to Needs review withdraws it from students again.
    assert client.patch(f"/api/v1/change-radar/reviews/{review['id']}", headers=admin.headers, json={"status": "needs_review"}).status_code == 200
    assert _twin(client, student)["assessments"] == []


def test_impact_twin_requires_sign_in_and_gives_administrators_no_cohort_view(twin_env):
    client, _db, admin, _student, _other, _staff, _old, _new = twin_env
    assert client.get("/api/v1/impact-twin").status_code == 401
    admin_view = _twin(client, admin)
    assert admin_view["cohort"] is None and admin_view["assessments"] == []
