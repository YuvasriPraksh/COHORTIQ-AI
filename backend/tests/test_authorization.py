"""Role-based access control for regulation and query endpoints (Part 4, Stage 4).

All requests use real accounts in a temporary database, signed in through the
login service; nothing overrides ``get_current_user``. Gemini is replaced by a
recorder so tests can see exactly which evidence reached answer generation.
The route-by-route anonymous/student/administrator matrix is in
``test_route_permissions.py``; this module covers behaviour and escalation.
"""

from __future__ import annotations

import base64
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

import fitz
import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import config as app_config
from app.database import get_regulation_by_id, init_database, insert_document_pages, insert_regulation
from app.models import GroundedAnswer, GroundedCitation
from backend.app.api.deps import FORBIDDEN_DETAIL, NOT_AUTHENTICATED_DETAIL, AuthenticatedUser
from backend.app.api.permissions import COHORT_FORBIDDEN_DETAIL, ensure_cohort_access
from backend.app.api.v1 import query as query_routes
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.auth.models import ROLE_ADMINISTRATOR, ROLE_STUDENT
from backend.app.auth.repository import deactivate_user, increment_token_version, update_user
from backend.app.core.security import create_access_token
from backend.app.main import app
from backend.app.services import query_service, regulation_service
from backend.tests.auth_support import SignedInAccount, create_signed_in_account, make_auth_settings, use_auth_database

API = "/api/v1"
ASK_URL = f"{API}/query/ask"
INGEST_URL = f"{API}/regulations/ingest"
BATCH, PROGRAMME = "2024", "BSc CS"
NOT_FOUND = {"detail": "Regulation not found"}


@pytest.fixture(autouse=True)
def _real_database_untouched() -> Iterator[None]:
    real_db = Path(app_config.get_settings().database_path).resolve()
    before = (real_db.stat().st_size, real_db.stat().st_mtime_ns) if real_db.exists() else None
    yield
    after = (real_db.stat().st_size, real_db.stat().st_mtime_ns) if real_db.exists() else None
    assert after == before, "The real project database was modified."


def _seed(db_path: Path, name: str, status: Optional[str], batches: list[str], programmes: list[str], text: str) -> int:
    regulation_id = insert_regulation(
        {
            "document_name": name,
            "regulation_version": "v1",
            "effective_date": "2024-08-01",
            "applicable_batches": batches,
            "applicable_programmes": programmes,
            "upload_date": "2024-08-01",
            "total_pages": 1,
            "processing_status": "extracted",
            "verification_status": status,
        },
        db_path=db_path,
    )
    insert_document_pages(
        regulation_id,
        [{"page_number": 1, "extracted_text": text, "extraction_status": "success"}],
        db_path=db_path,
    )
    return regulation_id


class Env:
    def __init__(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.db_path = db_path
        self.settings = make_auth_settings()
        self.client = TestClient(app)
        self.generation_calls: list[dict[str, Any]] = []
        self._accounts: dict[str, SignedInAccount] = {}
        use_auth_database(app, monkeypatch, db_path, self.settings)
        monkeypatch.setitem(app.dependency_overrides, regulation_routes.get_db_path, lambda: str(db_path))
        monkeypatch.setitem(app.dependency_overrides, query_routes.get_db_path, lambda: str(db_path))
        monkeypatch.setattr("app.workflow.generate_grounded_answer", self._record_generation)

        text = "Students must maintain at least 75 percent attendance in every course to sit examinations."
        self.approved = _seed(db_path, "Approved Attendance Rules", "approved", [BATCH], [PROGRAMME], text)
        self.pending = _seed(db_path, "Pending Draft Attendance", "pending", [BATCH], [PROGRAMME], text + " Draft.")
        self.rejected = _seed(db_path, "Rejected Attendance Proposal", "rejected", [BATCH], [PROGRAMME], text + " Rejected.")
        self.unreviewed = _seed(db_path, "Unreviewed Attendance Upload", None, [BATCH], [PROGRAMME], text + " Unreviewed.")
        self.verified = _seed(db_path, "Verified Exam Rules", "Verified", [BATCH], [PROGRAMME], "Examinations are held twice a year.")
        self.other_cohort = _seed(db_path, "Economics Attendance Rules", "approved", ["2023"], ["BA Econ"], text)
        self.pending_only_cohort = _seed(db_path, "MSc Draft Rules", "pending", ["2025"], ["MSc DS"], text)
        self.student_visible = {self.approved, self.verified, self.other_cohort}
        self.hidden = {self.pending, self.rejected, self.unreviewed, self.pending_only_cohort}

    def _record_generation(self, **kwargs: Any) -> GroundedAnswer:
        self.generation_calls.append(kwargs)
        first = dict(kwargs["evidence_chunks"][0])
        supporting = str(first.get("chunk_text") or "")[:80].strip()
        return GroundedAnswer(
            answer="Students must maintain the required attendance.",
            status="answered",
            citations=[
                GroundedCitation(
                    document_name=first.get("document_name"),
                    regulation_version=first.get("regulation_version"),
                    page_number=first.get("page_number"),
                    chunk_id=str(first.get("chunk_id")) if first.get("chunk_id") is not None else None,
                    relevant_supporting_text=supporting,
                )
            ],
            limitations=None,
        )

    def account(self, name: str) -> SignedInAccount:
        """Accounts are created on first use, each with its own random password."""
        if name not in self._accounts:
            options: dict[str, Any] = {
                "admin": {"role": ROLE_ADMINISTRATOR},
                "student": {"role": ROLE_STUDENT, "admission_batch": BATCH, "programme": PROGRAMME},
                "econ_student": {"role": ROLE_STUDENT, "admission_batch": "2023", "programme": "BA Econ"},
                "msc_student": {"role": ROLE_STUDENT, "admission_batch": "2025", "programme": "MSc DS"},
                "no_cohort_student": {"role": ROLE_STUDENT},
                "inactive_student": {"role": ROLE_STUDENT, "admission_batch": BATCH, "programme": PROGRAMME, "is_active": False},
            }[name]
            role = options.pop("role")
            self._accounts[name] = create_signed_in_account(self.db_path, self.settings, role, **options)
        return self._accounts[name]

    def get(self, path: str, who: Optional[str] = None, token: Optional[str] = None) -> Any:
        return self.client.get(path, headers=self._headers(who, token))

    def ask(self, who: Optional[str], *, batch: str = BATCH, programme: str = PROGRAMME, token: Optional[str] = None, **extra: Any) -> Any:
        body = {"question": "What attendance is required to sit examinations?", "admission_batch": batch, "programme": programme, **extra}
        return self.client.post(ASK_URL, json=body, headers=self._headers(who, token))

    def set_status(self, regulation_id: int, status: str, who: Optional[str]) -> Any:
        return self.client.patch(
            f"{API}/regulations/{regulation_id}/verification", json={"verification_status": status}, headers=self._headers(who)
        )

    def _headers(self, who: Optional[str], token: Optional[str] = None) -> dict[str, str]:
        if token is not None:
            return {"Authorization": f"Bearer {token}"}
        return self.account(who).headers if who else {}

    def status_of(self, regulation_id: int) -> Optional[str]:
        return get_regulation_by_id(regulation_id, db_path=self.db_path)["verification_status"]


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    db_path = tmp_path / "rbac.db"
    init_database(db_path)
    return Env(db_path, monkeypatch)


def _ids(response: Any) -> set[int]:
    assert response.status_code == 200, response.text
    return {regulation["id"] for regulation in response.json()["regulations"]}


def _assert_forbidden(response: Any, detail: str = FORBIDDEN_DETAIL) -> None:
    assert response.status_code == 403
    assert response.json() == {"detail": detail}


def _assert_unauthenticated(response: Any) -> None:
    assert response.status_code == 401
    assert response.json() == {"detail": NOT_AUTHENTICATED_DETAIL}
    assert response.headers["www-authenticate"] == "Bearer"


def _pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    document.new_page().insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def _ingest(env: Env, who: Optional[str]) -> Any:
    return env.client.post(
        INGEST_URL,
        files={"file": ("rules.pdf", _pdf_bytes("Students must attend all laboratory sessions."), "application/pdf")},
        data={
            "document_name": "Laboratory Rules",
            "regulation_version": "2025",
            "effective_date": "2025-01-01",
            "applicable_batches": [BATCH],
            "applicable_programmes": [PROGRAMME],
        },
        headers=env._headers(who),
    )


# --------------------------------------------------------------------------- #
# Regulation reads
# --------------------------------------------------------------------------- #


def test_student_lists_approved_regulations_only(env: Env) -> None:
    assert _ids(env.get(f"{API}/regulations", "student")) == env.student_visible


def test_administrator_lists_every_regulation(env: Env) -> None:
    assert _ids(env.get(f"{API}/regulations", "admin")) == env.student_visible | env.hidden


@pytest.mark.parametrize("name", ["approved", "verified", "other_cohort"])
def test_student_reads_approved_regulation_details_and_pages(env: Env, name: str) -> None:
    regulation_id = getattr(env, name)

    detail = env.get(f"{API}/regulations/{regulation_id}", "student")
    pages = env.get(f"{API}/regulations/{regulation_id}/pages", "student")

    assert detail.status_code == 200 and detail.json()["regulation"]["id"] == regulation_id
    assert pages.status_code == 200 and len(pages.json()["pages"]) == 1


@pytest.mark.parametrize("name", ["pending", "rejected", "unreviewed"])
def test_unapproved_regulations_look_missing_to_students(env: Env, name: str) -> None:
    regulation_id = getattr(env, name)
    missing_detail = env.get(f"{API}/regulations/999999", "student")
    missing_pages = env.get(f"{API}/regulations/999999/pages", "student")

    detail = env.get(f"{API}/regulations/{regulation_id}", "student")
    pages = env.get(f"{API}/regulations/{regulation_id}/pages", "student")

    for hidden, missing in ((detail, missing_detail), (pages, missing_pages)):
        assert hidden.status_code == missing.status_code == 404
        assert hidden.json() == missing.json() == NOT_FOUND
        assert hidden.headers.get("content-length") == missing.headers.get("content-length")
    assert "Draft" not in pages.text and "Rejected" not in pages.text


@pytest.mark.parametrize("name", ["pending", "rejected", "unreviewed"])
def test_administrator_reads_unapproved_regulations_and_pages(env: Env, name: str) -> None:
    regulation_id = getattr(env, name)

    detail = env.get(f"{API}/regulations/{regulation_id}", "admin")
    pages = env.get(f"{API}/regulations/{regulation_id}/pages", "admin")

    assert detail.status_code == 200 and detail.json()["regulation"]["id"] == regulation_id
    assert pages.status_code == 200 and len(pages.json()["pages"]) == 1


def test_student_visibility_uses_the_retrieval_approval_rule(env: Env) -> None:
    variants = {
        "APPROVED": True,
        " approved ": True,
        "administrator_verified": True,
        "approved-pending": False,
        "under review": False,
        "": False,
    }
    created = {
        status: _seed(env.db_path, f"Variant {index}", status, [BATCH], [PROGRAMME], "Variant text.")
        for index, status in enumerate(variants)
    }

    visible = _ids(env.get(f"{API}/regulations", "student"))

    for status, expected in variants.items():
        assert (created[status] in visible) is expected, status
        expected_code = 200 if expected else 404
        assert env.get(f"{API}/regulations/{created[status]}", "student").status_code == expected_code, status


def test_invalid_regulation_id_is_422_when_authenticated_and_401_when_anonymous(env: Env) -> None:
    assert env.get(f"{API}/regulations/not-a-number", "student").status_code == 422
    _assert_unauthenticated(env.get(f"{API}/regulations/not-a-number"))


# --------------------------------------------------------------------------- #
# Regulation management
# --------------------------------------------------------------------------- #


def test_student_cannot_upload_a_regulation(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def must_not_run(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("ingestion must not run for a student")

    monkeypatch.setattr(regulation_service, "ingest_regulation", must_not_run)
    before = _ids(env.get(f"{API}/regulations", "admin"))

    _assert_forbidden(_ingest(env, "student"))

    assert _ids(env.get(f"{API}/regulations", "admin")) == before


@pytest.mark.parametrize("target, status", [("pending", "approved"), ("approved", "rejected"), ("rejected", "pending"), ("pending", "rejected")])
def test_student_cannot_change_verification_status(env: Env, target: str, status: str) -> None:
    regulation_id = getattr(env, target)
    original = env.status_of(regulation_id)

    _assert_forbidden(env.set_status(regulation_id, status, "student"))

    assert env.status_of(regulation_id) == original


def test_student_cannot_probe_regulation_ids_through_verification(env: Env) -> None:
    for regulation_id in (env.pending, 999999):
        _assert_forbidden(env.set_status(regulation_id, "approved", "student"))


@pytest.mark.parametrize("status", ["approved", "rejected", "pending"])
def test_administrator_changes_verification_status(env: Env, status: str) -> None:
    response = env.set_status(env.unreviewed, status, "admin")

    assert response.status_code == 200
    assert env.status_of(env.unreviewed) == status


def test_review_workflow_controls_what_students_see(env: Env) -> None:
    ingested = _ingest(env, "admin")
    assert ingested.status_code == 200, ingested.text
    new_id = ingested.json()["regulation_id"]
    assert env.status_of(new_id) == "pending"
    assert env.get(f"{API}/regulations/{new_id}", "student").status_code == 404

    assert env.set_status(new_id, "approved", "admin").status_code == 200
    assert env.get(f"{API}/regulations/{new_id}/pages", "student").status_code == 200
    assert new_id in _ids(env.get(f"{API}/cohorts/{BATCH}/{PROGRAMME}/regulations", "student"))

    assert env.set_status(new_id, "rejected", "admin").status_code == 200
    assert env.get(f"{API}/regulations/{new_id}", "student").status_code == 404
    assert new_id not in _ids(env.get(f"{API}/regulations", "student"))


# --------------------------------------------------------------------------- #
# Cohort regulations
# --------------------------------------------------------------------------- #


def test_student_views_own_cohort_regulations(env: Env) -> None:
    assert _ids(env.get(f"{API}/cohorts/{BATCH}/{PROGRAMME}/regulations", "student")) == {env.approved, env.verified}


@pytest.mark.parametrize(
    "batch, programme",
    [("2023", "BA Econ"), (BATCH, "BA Econ"), ("2023", PROGRAMME), ("2024 ", PROGRAMME), (BATCH, "bsc cs"), (BATCH, "BSc%20CS%20")],
)
def test_student_cannot_view_another_cohort(env: Env, batch: str, programme: str) -> None:
    response = env.get(f"{API}/cohorts/{batch}/{programme}/regulations", "student")

    _assert_forbidden(response, COHORT_FORBIDDEN_DETAIL)
    assert "Economics" not in response.text


def test_student_without_a_cohort_is_refused(env: Env) -> None:
    _assert_forbidden(env.get(f"{API}/cohorts/{BATCH}/{PROGRAMME}/regulations", "no_cohort_student"), COHORT_FORBIDDEN_DETAIL)
    _assert_forbidden(env.ask("no_cohort_student"), COHORT_FORBIDDEN_DETAIL)


def test_administrator_views_any_cohort_approved_only(env: Env) -> None:
    assert _ids(env.get(f"{API}/cohorts/2023/BA Econ/regulations", "admin")) == {env.other_cohort}
    assert _ids(env.get(f"{API}/cohorts/2025/MSc DS/regulations", "admin")) == set()


def test_cohort_comes_from_the_database_account(env: Env) -> None:
    student = env.account("student")
    update_user(int(student.user.id), admission_batch="2023", programme="BA Econ", db_path=env.db_path)

    # Same token: the cohort is read from the users table on every request.
    _assert_forbidden(env.get(f"{API}/cohorts/{BATCH}/{PROGRAMME}/regulations", "student"), COHORT_FORBIDDEN_DETAIL)
    assert _ids(env.get(f"{API}/cohorts/2023/BA Econ/regulations", "student")) == {env.other_cohort}


# --------------------------------------------------------------------------- #
# AI query
# --------------------------------------------------------------------------- #


def test_student_asks_about_own_cohort_with_approved_evidence_only(env: Env) -> None:
    response = env.ask("student")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "answered"
    [call] = env.generation_calls
    assert (call["admission_batch"], call["programme"]) == (BATCH, PROGRAMME)
    used = {chunk["document_name"] for chunk in call["evidence_chunks"]}
    assert used <= {"Approved Attendance Rules", "Verified Exam Rules"}
    for name in ("Pending", "Rejected", "Unreviewed", "Economics"):
        assert name not in response.text
        assert all(name not in str(chunk) for chunk in call["evidence_chunks"])


def test_student_cohort_with_only_unapproved_documents_gets_no_evidence(env: Env) -> None:
    response = env.ask("msc_student", batch="2025", programme="MSc DS")

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["citations"] == []
    assert env.generation_calls == []
    assert "MSc Draft" not in response.text


@pytest.mark.parametrize(
    "batch, programme",
    [("2023", PROGRAMME), (BATCH, "BA Econ"), ("2023", "BA Econ"), (BATCH, "bsc cs"), ("2025", "MSc DS")],
    ids=["forged-batch", "forged-programme", "forged-both", "case-variant", "pending-only-cohort"],
)
def test_student_cannot_query_another_cohort(env: Env, monkeypatch: pytest.MonkeyPatch, batch: str, programme: str) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(query_service, "answer_student_regulation_question", lambda **kwargs: calls.append(kwargs))

    response = env.ask("student", batch=batch, programme=programme)

    _assert_forbidden(response, COHORT_FORBIDDEN_DETAIL)
    assert calls == [] and env.generation_calls == []


def test_query_uses_the_stored_cohort_values(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    real = query_service.answer_student_regulation_question
    monkeypatch.setattr(query_service, "answer_student_regulation_question", lambda **kw: calls.append(kw) or real(**kw))

    assert env.ask("student", batch=f"  {BATCH}  ", programme=f" {PROGRAMME} ").status_code == 200

    assert (calls[0]["admission_batch"], calls[0]["programme"]) == (BATCH, PROGRAMME)


def test_role_in_request_body_grants_nothing(env: Env) -> None:
    _assert_forbidden(env.ask("student", batch="2023", programme="BA Econ", role="administrator"), COHORT_FORBIDDEN_DETAIL)
    assert env.ask("student", role="administrator", is_admin=True).status_code == 200

    response = env.client.patch(
        f"{API}/regulations/{env.pending}/verification",
        json={"verification_status": "approved", "role": "administrator"},
        headers=env.account("student").headers,
    )
    _assert_forbidden(response)
    assert env.status_of(env.pending) == "pending"


def test_administrator_queries_any_cohort(env: Env) -> None:
    response = env.ask("admin", batch="2023", programme="BA Econ")

    assert response.status_code == 200 and response.json()["status"] == "answered"
    [call] = env.generation_calls
    assert (call["admission_batch"], call["programme"]) == ("2023", "BA Econ")
    assert {chunk["document_name"] for chunk in call["evidence_chunks"]} == {"Economics Attendance Rules"}


def test_administrator_queries_never_use_unapproved_evidence(env: Env) -> None:
    response = env.ask("admin", batch="2025", programme="MSc DS")

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert env.generation_calls == []


# --------------------------------------------------------------------------- #
# Account state and token tampering
# --------------------------------------------------------------------------- #


def _protected_requests(env: Env, token: str) -> list[Any]:
    return [
        env.get(f"{API}/regulations", token=token),
        env.get(f"{API}/regulations/{env.approved}/pages", token=token),
        env.get(f"{API}/cohorts/{BATCH}/{PROGRAMME}/regulations", token=token),
        env.ask(None, token=token),
    ]


def test_inactive_account_is_refused_everywhere(env: Env) -> None:
    for response in _protected_requests(env, env.account("inactive_student").token):
        _assert_unauthenticated(response)


@pytest.mark.parametrize(
    "revoke",
    [
        lambda env, user_id: increment_token_version(user_id, db_path=env.db_path),
        lambda env, user_id: deactivate_user(user_id, db_path=env.db_path),
        lambda env, user_id: update_user(user_id, role=ROLE_ADMINISTRATOR, db_path=env.db_path),
    ],
    ids=["token-version", "deactivated", "role-changed"],
)
def test_revoked_tokens_are_refused_everywhere(env: Env, revoke: Any) -> None:
    student = env.account("student")
    assert env.get(f"{API}/regulations", token=student.token).status_code == 200

    revoke(env, student.user.id)

    for response in _protected_requests(env, student.token):
        _assert_unauthenticated(response)


def test_expired_token_is_refused(env: Env) -> None:
    student = env.account("student")
    expired = create_access_token(
        student.user.id,
        student.user.token_version,
        settings=env.settings,
        expires_delta=timedelta(minutes=5),
        now=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    for response in _protected_requests(env, expired):
        _assert_unauthenticated(response)
    _assert_unauthenticated(_ingest_with_token(env, expired))


def _ingest_with_token(env: Env, token: str) -> Any:
    return env.client.post(INGEST_URL, files={"file": ("x.pdf", _pdf_bytes("x"), "application/pdf")}, headers={"Authorization": f"Bearer {token}"})


def test_validly_signed_role_claim_is_ignored(env: Env) -> None:
    student = env.account("student")
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(student.user.id),
        "ver": student.user.token_version,
        "jti": secrets.token_hex(16),
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=5),
        "iss": env.settings.jwt_issuer,
        "aud": env.settings.jwt_audience,
        "role": ROLE_ADMINISTRATOR,
        "admission_batch": "2023",
        "programme": "BA Econ",
    }
    forged = jwt.encode(claims, env.settings.jwt_secret_key, algorithm="HS256")

    _assert_forbidden(_ingest_with_token(env, forged))
    assert _ids(env.get(f"{API}/regulations", token=forged)) == env.student_visible
    _assert_forbidden(env.get(f"{API}/cohorts/2023/BA Econ/regulations", token=forged), COHORT_FORBIDDEN_DETAIL)
    _assert_forbidden(env.ask(None, batch="2023", programme="BA Econ", token=forged), COHORT_FORBIDDEN_DETAIL)


def _tamper(token: str, **changes: Any) -> str:
    header, payload, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims.update(changes)
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{encoded}.{signature}"


def test_tampered_tokens_are_refused(env: Env) -> None:
    student = env.account("student")
    admin = env.account("admin")

    for forged in (
        _tamper(student.token, role=ROLE_ADMINISTRATOR),
        _tamper(student.token, sub=str(admin.user.id)),
        jwt.encode({"sub": str(admin.user.id), "ver": 0}, "not-the-server-secret-" + secrets.token_hex(16), algorithm="HS256"),
        jwt.encode({"sub": str(admin.user.id), "ver": 0}, key="", algorithm="none"),
    ):
        _assert_unauthenticated(_ingest_with_token(env, forged))
        _assert_unauthenticated(env.get(f"{API}/regulations", token=forged))


# --------------------------------------------------------------------------- #
# ensure_cohort_access (defence in depth below get_current_user)
# --------------------------------------------------------------------------- #


def _user(role: str, batch: Optional[str] = BATCH, programme: Optional[str] = PROGRAMME) -> AuthenticatedUser:
    return AuthenticatedUser(id="1", role=role, is_active=True, token_version=0, admission_batch=batch, programme=programme)


def test_cohort_check_admits_administrators_for_any_cohort() -> None:
    assert ensure_cohort_access(_user(ROLE_ADMINISTRATOR, None, None), "2023", "BA Econ") == ("2023", "BA Econ")


def test_cohort_check_returns_the_stored_values_for_a_matching_student() -> None:
    assert ensure_cohort_access(_user(ROLE_STUDENT), BATCH, PROGRAMME) == (BATCH, PROGRAMME)


@pytest.mark.parametrize(
    "user",
    [
        _user("superuser"),
        _user("Administrator"),
        _user(""),
        _user(ROLE_STUDENT, None, PROGRAMME),
        _user(ROLE_STUDENT, BATCH, None),
        _user(ROLE_STUDENT, "", ""),
    ],
    ids=["unknown-role", "role-case-variant", "empty-role", "no-batch", "no-programme", "blank-cohort"],
)
def test_cohort_check_fails_closed(user: AuthenticatedUser) -> None:
    with pytest.raises(HTTPException) as excinfo:
        ensure_cohort_access(user, user.admission_batch or BATCH, user.programme or PROGRAMME)

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == COHORT_FORBIDDEN_DETAIL
