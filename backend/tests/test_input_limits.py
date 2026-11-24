"""API input limits (Part 3.9).

Covers request-size protection (ASGI middleware), query field validation,
upload size and page limits, ingestion metadata limits, safe 422 responses,
environment-variable configuration and Streamlit compatibility.

All tests use temporary databases and files. Gemini is always replaced by a
recorder, so no external call can be made.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import tempfile as std_tempfile
from pathlib import Path
from typing import Any, Callable, Iterator

import fitz
import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app import workflow
from app.database import get_all_regulations, get_document_pages, init_database, insert_regulation_with_pages
from app.models import GroundedAnswer
from backend.app import main as main_module
from backend.app.api.v1 import query as query_routes
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.core.config import MIB, Settings, get_settings
from backend.app.core.limits import BodyLimit, RequestSizeLimitMiddleware
from backend.app.main import app
from backend.app.services import query_service, regulation_service

LIMITS = get_settings()
ASK_URL = "/api/v1/query/ask"
INGEST_URL = "/api/v1/regulations/ingest"
BATCH = "2024"
PROGRAMME = "BSc CS"
PLANTED = "PLANTED-INPUT-MARKER-9f3c"

VALID_METADATA: dict[str, Any] = {
    "document_name": "Academic Regulations",
    "regulation_version": "R2024",
    "effective_date": "2024-08-01",
    "applicable_batches": [BATCH],
    "applicable_programmes": [PROGRAMME],
}


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #


class Env:
    def __init__(self, client: TestClient, db_path: Path) -> None:
        self.client = client
        self.db_path = db_path
        self.generation_calls: list[dict[str, Any]] = []
        self.ingest_calls: list[Path] = []
        self.temp_files: list[Path] = []

    def ask(self, **overrides: Any):
        payload = {
            "question": "What is the attendance requirement?",
            "admission_batch": BATCH,
            "programme": PROGRAMME,
            **overrides,
        }
        return self.client.post(ASK_URL, json=payload)

    def upload(
        self,
        content: bytes,
        *,
        data: dict[str, Any] | None = None,
        files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
    ):
        return self.client.post(
            INGEST_URL,
            data=VALID_METADATA if data is None else data,
            files=files if files is not None else [("file", ("regulation.pdf", content, "application/pdf"))],
        )

    def stored_regulation_count(self) -> int:
        return len(get_all_regulations(self.db_path))

    def assert_no_temp_files_left(self) -> None:
        for path in self.temp_files:
            assert not path.exists(), f"Temporary upload left behind: {path}"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    db_path = tmp_path / "limits.db"
    init_database(db_path)
    insert_regulation_with_pages(
        {
            "document_name": "Attendance Rules",
            "regulation_version": "R2024",
            "effective_date": "2024-08-01",
            "applicable_batches": [BATCH],
            "applicable_programmes": [PROGRAMME],
            "upload_date": "2024-07-01",
            "verification_status": "approved",
        },
        [{"page_number": 1, "text": "Students must maintain 75 percent attendance in each course.", "status": "success"}],
        db_path=db_path,
    )
    environment = Env(TestClient(app), db_path)

    def recording_generation(**kwargs: Any) -> GroundedAnswer:
        environment.generation_calls.append(kwargs)
        return GroundedAnswer(answer="Test double.", status="insufficient_evidence", limitations="Test double.")

    monkeypatch.setattr("app.workflow.generate_grounded_answer", recording_generation)

    real_ingest = regulation_service.ingest_regulation

    def recording_ingest(pdf_path: Any, metadata: Any, db_path: Any = None) -> dict[str, Any]:
        environment.ingest_calls.append(Path(pdf_path))
        return real_ingest(pdf_path=pdf_path, metadata=metadata, db_path=db_path)

    monkeypatch.setattr(regulation_service, "ingest_regulation", recording_ingest)

    real_named_temporary_file = std_tempfile.NamedTemporaryFile

    def recording_named_temporary_file(*args: Any, **kwargs: Any) -> Any:
        handle = real_named_temporary_file(*args, **kwargs)
        environment.temp_files.append(Path(handle.name))
        return handle

    monkeypatch.setattr(regulation_routes.tempfile, "NamedTemporaryFile", recording_named_temporary_file)

    app.dependency_overrides[regulation_routes.get_db_path] = lambda: str(db_path)
    app.dependency_overrides[query_routes.get_db_path] = lambda: str(db_path)
    try:
        yield environment
    finally:
        app.dependency_overrides.pop(regulation_routes.get_db_path, None)
        app.dependency_overrides.pop(query_routes.get_db_path, None)
        app.dependency_overrides.pop(regulation_routes.get_api_settings, None)


def _pdf_bytes(pages: int = 1, text: str | None = "Attendance rule.") -> bytes:
    document = fitz.open()
    try:
        for _ in range(pages):
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        return document.tobytes(garbage=3, deflate=True)
    finally:
        document.close()


def _assert_safe_422(response: Any, *forbidden: str) -> list[dict[str, Any]]:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    for error in detail:
        assert set(error) == {"type", "loc", "msg"}, error
    for marker in forbidden:
        assert marker not in response.text, f"422 response echoed {marker!r}"
    return detail


def _http_scope(path: str, headers: list[tuple[bytes, bytes]], method: str = "POST") -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }


def _run_asgi(asgi_app: Any, scope: dict[str, Any], receive: Callable[[], Any]) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(asgi_app(scope, receive, send))
    return sent


def _status_of(messages: list[dict[str, Any]]) -> int:
    starts = [m for m in messages if m["type"] == "http.response.start"]
    assert len(starts) == 1, messages
    return starts[0]["status"]


def _body_of(messages: list[dict[str, Any]]) -> bytes:
    return b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")


def _multipart_body(file_bytes: bytes, fields: dict[str, Any] | None = None) -> tuple[bytes, str]:
    boundary = "cohortiq-test-boundary-7d1e"
    parts: list[bytes] = []
    for name, value in (fields or VALID_METADATA).items():
        for item in value if isinstance(value, list) else [value]:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{item}\r\n'.encode()
            )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="regulation.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n".encode()
        + file_bytes
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _streamed(body: bytes, piece: int = 256 * 1024) -> Iterator[bytes]:
    for start in range(0, len(body), piece):
        yield body[start : start + piece]


# --------------------------------------------------------------------------- #
# 1-4. Query field boundaries, strict integers, strategies, no Gemini on 422
# --------------------------------------------------------------------------- #


QUERY_BOUNDARIES = [
    # top_k: 1..20
    ({"top_k": 0}, 422), ({"top_k": 1}, 200), ({"top_k": 2}, 200),
    ({"top_k": 19}, 200), ({"top_k": 20}, 200), ({"top_k": 21}, 422),
    # chunk_size: 200..4000 (overlap 0 so only chunk_size is under test)
    ({"chunk_size": 199, "overlap": 0}, 422), ({"chunk_size": 200, "overlap": 0}, 200),
    ({"chunk_size": 201, "overlap": 0}, 200), ({"chunk_size": 3999, "overlap": 0}, 200),
    ({"chunk_size": 4000, "overlap": 0}, 200), ({"chunk_size": 4001, "overlap": 0}, 422),
    # overlap: 0..1000 (chunk_size 4000 so only overlap is under test)
    ({"overlap": -1, "chunk_size": 4000}, 422), ({"overlap": 0, "chunk_size": 4000}, 200),
    ({"overlap": 1, "chunk_size": 4000}, 200), ({"overlap": 999, "chunk_size": 4000}, 200),
    ({"overlap": 1000, "chunk_size": 4000}, 200), ({"overlap": 1001, "chunk_size": 4000}, 422),
    # overlap strictly below chunk_size
    ({"chunk_size": 500, "overlap": 499}, 200), ({"chunk_size": 500, "overlap": 500}, 422),
    ({"chunk_size": 500, "overlap": 501}, 422),
    # question: max 2000 characters
    ({"question": "q" * 1999}, 200), ({"question": "q" * 2000}, 200), ({"question": "q" * 2001}, 422),
    # admission_batch / programme: max 100 characters
    ({"admission_batch": "b" * 99}, 200), ({"admission_batch": "b" * 100}, 200),
    ({"admission_batch": "b" * 101}, 422),
    ({"programme": "p" * 99}, 200), ({"programme": "p" * 100}, 200), ({"programme": "p" * 101}, 422),
]


@pytest.mark.parametrize(("overrides", "expected"), QUERY_BOUNDARIES, ids=lambda v: str(v)[:40])
def test_query_field_boundaries(env: Env, overrides: dict[str, Any], expected: int) -> None:
    response = env.ask(**overrides)

    assert response.status_code == expected, response.text
    if expected == 422:
        _assert_safe_422(response)
        assert env.generation_calls == [], "Gemini must not be called for an invalid request."


@pytest.mark.parametrize("field", ["top_k", "chunk_size", "overlap"])
@pytest.mark.parametrize(
    "value",
    ["7", "300", True, False, 5.5, 300.0, None, "abc", [5], {"value": 5}],
    ids=["numeric_string", "numeric_string_2", "true", "false", "decimal", "whole_float", "null", "text", "list", "object"],
)
def test_integer_fields_are_strict(env: Env, field: str, value: Any) -> None:
    response = env.ask(**{field: value})

    _assert_safe_422(response)
    assert env.generation_calls == []


@pytest.mark.parametrize(
    "strategy",
    ["recursive", "fixed_size", "fixed", "fixed-size", "Fixed Size", "semantic", "semantic-style", "SEMANTIC_STYLE"],
)
def test_supported_chunking_strategies_and_aliases_are_accepted(env: Env, strategy: str) -> None:
    response = env.ask(chunking_strategy=strategy)

    assert response.status_code == 200, response.text
    assert len(env.generation_calls) == 1


@pytest.mark.parametrize("strategy", ["bogus", "", "   ", "x" * 51, 7, None])
def test_unsupported_chunking_strategies_are_rejected(env: Env, strategy: Any) -> None:
    response = env.ask(chunking_strategy=strategy)

    _assert_safe_422(response)
    assert env.generation_calls == []


def test_defaults_are_unchanged(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    forwarded: dict[str, Any] = {}
    real_answer = query_service.answer_student_regulation_question

    def recording_answer(**kwargs: Any) -> dict[str, Any]:
        forwarded.update(kwargs)
        return real_answer(**kwargs)

    monkeypatch.setattr(query_service, "answer_student_regulation_question", recording_answer)

    response = env.client.post(
        ASK_URL, json={"question": "Attendance?", "admission_batch": BATCH, "programme": PROGRAMME}
    )

    assert response.status_code == 200
    assert forwarded["top_k"] == 5
    assert forwarded["chunking_strategy"] == "recursive"
    assert forwarded["chunk_size"] == 1000
    assert forwarded["overlap"] == 200


def test_blank_question_still_returns_400(env: Env) -> None:
    response = env.ask(question="   ")

    assert response.status_code == 400
    assert response.json() == {"detail": "question, admission_batch, and programme are required."}


# --------------------------------------------------------------------------- #
# 5-7. Request-size middleware
# --------------------------------------------------------------------------- #


def _json_body_of_size(size: int) -> bytes:
    base = {"question": "Attendance?", "admission_batch": BATCH, "programme": PROGRAMME, "padding": ""}
    overhead = len(json.dumps(base).encode())
    base["padding"] = "x" * (size - overhead)
    body = json.dumps(base).encode()
    assert len(body) == size
    return body


def test_json_body_exactly_at_limit_is_accepted(env: Env) -> None:
    body = _json_body_of_size(LIMITS.max_json_body_bytes)

    response = env.client.post(ASK_URL, content=body, headers={"content-type": "application/json"})

    assert response.status_code == 200, response.text


def test_json_body_over_limit_is_rejected_with_413(env: Env) -> None:
    body = _json_body_of_size(LIMITS.max_json_body_bytes + 1)

    response = env.client.post(ASK_URL, content=body, headers={"content-type": "application/json"})

    assert response.status_code == 413
    assert response.json() == {"detail": main_module.REQUEST_TOO_LARGE_DETAIL}
    assert "64 KB" in response.json()["detail"]
    assert env.generation_calls == []


@pytest.mark.parametrize(
    ("path", "declared"),
    [
        (ASK_URL, LIMITS.max_json_body_bytes + 1),
        (INGEST_URL, LIMITS.max_upload_request_bytes + 1),
        (INGEST_URL, 10 * 1024 * MIB),
    ],
)
def test_oversized_content_length_is_rejected_before_reading_body(path: str, declared: int) -> None:
    receive_calls = 0

    async def receive() -> dict[str, Any]:
        nonlocal receive_calls
        receive_calls += 1
        raise AssertionError("The body must not be read when Content-Length is too large.")

    scope = _http_scope(
        path, [(b"content-type", b"application/json"), (b"content-length", str(declared).encode())]
    )
    messages = _run_asgi(app, scope, receive)

    assert _status_of(messages) == 413
    assert receive_calls == 0
    assert b"maximum allowed size" in _body_of(messages)


@pytest.mark.parametrize("value", [b"abc", b"-5", b"1.5", b""])
def test_malformed_content_length_returns_400(value: bytes) -> None:
    async def receive() -> dict[str, Any]:
        raise AssertionError("must not read")

    messages = _run_asgi(app, _http_scope(ASK_URL, [(b"content-length", value)]), receive)

    assert _status_of(messages) == 400
    assert json.loads(_body_of(messages)) == {"detail": "Invalid Content-Length header."}


def test_conflicting_content_length_headers_return_400() -> None:
    async def receive() -> dict[str, Any]:
        raise AssertionError("must not read")

    scope = _http_scope(ASK_URL, [(b"content-length", b"10"), (b"content-length", b"20")])

    assert _status_of(_run_asgi(app, scope, receive)) == 400


def test_streamed_body_without_content_length_stops_reading_at_limit(env: Env) -> None:
    piece = 8 * 1024
    limit = LIMITS.max_json_body_bytes
    received_calls = 0

    async def receive() -> dict[str, Any]:
        nonlocal received_calls
        received_calls += 1
        if received_calls > 1000:
            raise AssertionError("Middleware kept reading after the limit was exceeded.")
        return {"type": "http.request", "body": b"x" * piece, "more_body": True}

    messages = _run_asgi(app, _http_scope(ASK_URL, [(b"content-type", b"application/json")]), receive)

    assert _status_of(messages) == 413
    assert json.loads(_body_of(messages)) == {"detail": main_module.REQUEST_TOO_LARGE_DETAIL}
    # Reading stopped on the first message that crossed the limit.
    assert received_calls == math.floor(limit / piece) + 1
    assert env.generation_calls == []


def test_streamed_body_under_limit_is_passed_through_intact(env: Env) -> None:
    payload = json.dumps(
        {"question": "Streamed attendance question?", "admission_batch": BATCH, "programme": PROGRAMME}
    ).encode()
    pieces = [payload[i : i + 7] for i in range(0, len(payload), 7)]
    queue = [{"type": "http.request", "body": p, "more_body": True} for p in pieces]
    queue.append({"type": "http.request", "body": b"", "more_body": False})

    async def receive() -> dict[str, Any]:
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    messages = _run_asgi(app, _http_scope(ASK_URL, [(b"content-type", b"application/json")]), receive)

    assert _status_of(messages) == 200
    assert env.generation_calls[0]["question"] == "Streamed attendance question?"


def test_testclient_generator_upload_has_no_content_length() -> None:
    """Confirms the streamed-upload tests below really exercise the no-Content-Length path."""
    request = httpx.Request("POST", "http://testserver" + INGEST_URL, content=_streamed(b"x" * 10))
    assert "content-length" not in request.headers
    assert request.headers.get("transfer-encoding") == "chunked"


def _echo_app_factory(log: list[dict[str, Any]]):
    async def echo(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            log.append({"passthrough": scope["type"], "receive": receive, "send": send})
            return
        message = await receive()
        log.append(message)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return echo


def test_client_disconnect_is_passed_through_without_413() -> None:
    log: list[dict[str, Any]] = []
    middleware = RequestSizeLimitMiddleware(_echo_app_factory(log), default_limit=BodyLimit(10, "too big"))

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    messages = _run_asgi(middleware, _http_scope("/x", []), receive)

    assert log == [{"type": "http.disconnect"}]
    assert _status_of(messages) == 204


def test_non_http_scopes_are_passed_through_untouched() -> None:
    log: list[dict[str, Any]] = []
    middleware = RequestSizeLimitMiddleware(_echo_app_factory(log), default_limit=BodyLimit(10, "too big"))

    async def receive() -> dict[str, Any]:
        return {"type": "lifespan.startup"}

    async def send(_message: dict[str, Any]) -> None:
        return None

    asyncio.run(middleware({"type": "lifespan"}, receive, send))

    assert log[0]["passthrough"] == "lifespan"
    assert log[0]["receive"] is receive and log[0]["send"] is send


def test_response_already_started_is_not_replaced() -> None:
    async def streaming_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        while (await receive())["type"] == "http.request":
            pass
        await send({"type": "http.response.body", "body": b"done"})

    middleware = RequestSizeLimitMiddleware(streaming_app, default_limit=BodyLimit(10, "too big"))
    chunks = [{"type": "http.request", "body": b"x" * 8, "more_body": True} for _ in range(3)]

    async def receive() -> dict[str, Any]:
        return chunks.pop(0) if chunks else {"type": "http.disconnect"}

    messages = _run_asgi(middleware, _http_scope("/x", []), receive)

    assert _status_of(messages) == 200
    assert _body_of(messages) == b"done"


# --------------------------------------------------------------------------- #
# 8-9. Upload size limit and cleanup
# --------------------------------------------------------------------------- #


def _limits_with(**changes: Any) -> Settings:
    return dataclasses.replace(LIMITS, **changes)


def test_upload_exactly_at_limit_is_accepted(env: Env) -> None:
    pdf = _pdf_bytes()
    app.dependency_overrides[regulation_routes.get_api_settings] = lambda: _limits_with(max_upload_bytes=len(pdf))

    response = env.upload(pdf)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ingested"
    env.assert_no_temp_files_left()


def test_upload_one_byte_over_limit_is_rejected_and_cleaned_up(env: Env) -> None:
    pdf = _pdf_bytes()
    limits = _limits_with(max_upload_bytes=len(pdf) - 1)
    app.dependency_overrides[regulation_routes.get_api_settings] = lambda: limits

    response = env.upload(pdf)

    assert response.status_code == 413
    assert response.json() == {"detail": regulation_routes.upload_too_large_detail(limits)}
    assert env.ingest_calls == [], "Oversized uploads must never reach ingestion."
    assert env.stored_regulation_count() == 1  # only the seeded regulation
    assert len(env.temp_files) == 1
    env.assert_no_temp_files_left()


def test_default_limit_file_of_exactly_20_mb_passes_size_checks(env: Env) -> None:
    content = b"%PDF-1.7\n" + b"0" * (LIMITS.max_upload_bytes - 9)
    assert len(content) == 20 * MIB

    response = env.upload(content)

    # Not a real PDF, so it fails later as an unreadable PDF - but never as "too large".
    assert response.status_code == 422
    assert response.json() == {"detail": regulation_routes.INVALID_PDF_DETAIL}
    env.assert_no_temp_files_left()


def test_default_limit_file_one_byte_over_20_mb_is_rejected_by_route(env: Env) -> None:
    content = b"0" * (LIMITS.max_upload_bytes + 1)

    response = env.upload(content)

    # Within the multipart allowance, so the route's chunked copy enforces it.
    assert response.status_code == 413
    assert response.json() == {"detail": "The uploaded file exceeds the maximum allowed size of 20 MB."}
    assert env.ingest_calls == []
    assert len(env.temp_files) == 1
    env.assert_no_temp_files_left()


def test_upload_far_over_limit_is_rejected_by_middleware_before_any_temp_file(env: Env) -> None:
    content = b"0" * (LIMITS.max_upload_request_bytes + 1)

    response = env.upload(content)

    assert response.status_code == 413
    assert response.json() == {"detail": main_module.UPLOAD_TOO_LARGE_DETAIL}
    assert env.temp_files == [], "The route must not run for bodies over the request limit."
    assert env.ingest_calls == []


def test_streamed_upload_without_content_length_is_limited_by_route(env: Env) -> None:
    body, content_type = _multipart_body(b"0" * (LIMITS.max_upload_bytes + 1))

    response = env.client.post(INGEST_URL, content=_streamed(body), headers={"content-type": content_type})

    assert response.status_code == 413
    assert env.ingest_calls == []
    env.assert_no_temp_files_left()


def test_streamed_upload_without_content_length_is_limited_by_middleware(env: Env) -> None:
    body, content_type = _multipart_body(b"0" * (LIMITS.max_upload_request_bytes + 1))

    response = env.client.post(INGEST_URL, content=_streamed(body), headers={"content-type": content_type})

    assert response.status_code == 413
    assert response.json() == {"detail": main_module.UPLOAD_TOO_LARGE_DETAIL}
    assert env.temp_files == []


def test_streamed_valid_upload_without_content_length_succeeds(env: Env) -> None:
    body, content_type = _multipart_body(_pdf_bytes(pages=2))

    response = env.client.post(INGEST_URL, content=_streamed(body, piece=64), headers={"content-type": content_type})

    assert response.status_code == 200, response.text
    assert response.json()["extraction_summary"]["total_pages"] == 2
    env.assert_no_temp_files_left()


def test_upload_is_copied_in_bounded_chunks(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    read_sizes: list[Any] = []
    real_read = UploadFile.read

    async def recording_read(self: UploadFile, size: int = -1) -> bytes:
        read_sizes.append(size)
        return await real_read(self, size)

    monkeypatch.setattr(UploadFile, "read", recording_read)

    response = env.upload(b"%PDF-1.7\n" + b"0" * (3 * MIB))

    assert response.status_code == 422  # not a real PDF; size is what matters here
    assert read_sizes and all(size == regulation_routes.UPLOAD_COPY_CHUNK_BYTES for size in read_sizes)
    assert regulation_routes.UPLOAD_COPY_CHUNK_BYTES == 1 * MIB


# --------------------------------------------------------------------------- #
# 10. Page-count limit
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("pages", [499, 500])
def test_pdf_at_or_below_page_limit_is_accepted(env: Env, pages: int) -> None:
    response = env.upload(_pdf_bytes(pages=pages, text=None))

    assert response.status_code == 200, response.text
    regulation_id = response.json()["regulation_id"]
    assert len(get_document_pages(regulation_id, env.db_path)) == pages
    env.assert_no_temp_files_left()


def test_pdf_over_page_limit_is_rejected_before_extraction(env: Env) -> None:
    response = env.upload(_pdf_bytes(pages=501, text=None))

    assert response.status_code == 422
    assert response.json() == {"detail": "The PDF has too many pages. The maximum allowed is 500 pages."}
    assert env.ingest_calls == [], "The extraction workflow must not run."
    assert env.stored_regulation_count() == 1
    env.assert_no_temp_files_left()


def test_corrupted_pdf_still_reports_invalid_pdf(env: Env) -> None:
    response = env.upload(b"%PDF-1.7 not a real pdf")

    assert response.status_code == 422
    assert response.json() == {"detail": regulation_routes.INVALID_PDF_DETAIL}


# --------------------------------------------------------------------------- #
# 11-12. Ingestion metadata limits and single-file rule
# --------------------------------------------------------------------------- #


METADATA_BOUNDARIES = [
    ({"document_name": "d" * 199}, 200), ({"document_name": "d" * 200}, 200), ({"document_name": "d" * 201}, 422),
    ({"regulation_version": "v" * 49}, 200), ({"regulation_version": "v" * 50}, 200),
    ({"regulation_version": "v" * 51}, 422),
    ({"effective_date": "2024-08-01" + " " * 22}, 200),  # 32 characters, valid after trimming
    ({"effective_date": "2024-08-01" + " " * 23}, 422),  # 33 characters
    ({"applicable_batches": ["b" * 99]}, 200), ({"applicable_batches": ["b" * 100]}, 200),
    ({"applicable_batches": ["b" * 101]}, 422),
    ({"applicable_programmes": ["p" * 100]}, 200), ({"applicable_programmes": ["p" * 101]}, 422),
    ({"applicable_batches": [str(i) for i in range(49)]}, 200),
    ({"applicable_batches": [str(i) for i in range(50)]}, 200),
    ({"applicable_batches": [str(i) for i in range(51)]}, 422),
    ({"applicable_programmes": [f"P{i}" for i in range(50)]}, 200),
    ({"applicable_programmes": [f"P{i}" for i in range(51)]}, 422),
]


@pytest.mark.parametrize(("overrides", "expected"), METADATA_BOUNDARIES, ids=lambda v: str(v)[:40])
def test_metadata_boundaries(env: Env, overrides: dict[str, Any], expected: int) -> None:
    response = env.upload(_pdf_bytes(), data={**VALID_METADATA, **overrides})

    assert response.status_code == expected, response.text
    if expected == 422:
        _assert_safe_422(response)
        assert env.ingest_calls == []
        assert env.stored_regulation_count() == 1
    env.assert_no_temp_files_left()


@pytest.mark.parametrize(
    "value",
    ["2024-13-01", "2024-02-30", "01-08-2024", "2024-8-1", "2024/08/01", "August 1, 2024", "2024-08-01T00:00"],
)
def test_effective_date_must_be_a_real_iso_date(env: Env, value: str) -> None:
    response = env.upload(_pdf_bytes(), data={**VALID_METADATA, "effective_date": value})

    detail = _assert_safe_422(response, value)
    assert detail == [
        {
            "type": "value_error",
            "loc": ["body", "effective_date"],
            "msg": "effective_date must be a valid date in YYYY-MM-DD format.",
        }
    ]
    assert env.ingest_calls == []


@pytest.mark.parametrize("field", ["document_name", "regulation_version", "effective_date"])
def test_blank_metadata_still_returns_400(env: Env, field: str) -> None:
    response = env.upload(_pdf_bytes(), data={**VALID_METADATA, field: "   "})

    assert response.status_code == 400
    assert response.json() == {"detail": "Missing required metadata."}


def test_multiple_uploaded_files_are_rejected(env: Env) -> None:
    pdf = _pdf_bytes()
    response = env.upload(
        pdf,
        files=[
            ("file", ("one.pdf", pdf, "application/pdf")),
            ("file", ("two.pdf", pdf, "application/pdf")),
        ],
    )

    assert response.status_code == 400
    assert "Too many files" in response.json()["detail"]
    assert env.temp_files == [] and env.ingest_calls == []
    assert env.stored_regulation_count() == 1


def test_too_many_form_fields_are_rejected(env: Env) -> None:
    data = {**VALID_METADATA, "applicable_batches": [str(i) for i in range(LIMITS.max_form_fields)]}

    response = env.upload(_pdf_bytes(), data=data)

    assert response.status_code == 400
    assert "Too many fields" in response.json()["detail"]
    assert env.ingest_calls == []


def test_form_field_over_part_size_is_rejected(env: Env) -> None:
    data = {**VALID_METADATA, "upload_date": "x" * (LIMITS.max_form_part_size + 1)}

    response = env.upload(_pdf_bytes(), data=data)

    assert response.status_code == 400
    assert "maximum size" in response.json()["detail"]
    assert "x" * 100 not in response.text
    assert env.ingest_calls == []


# --------------------------------------------------------------------------- #
# 13. Safe 422 responses
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "overrides",
    [
        {"top_k": f"{PLANTED}-top-k"},
        {"question": PLANTED * 300},
        {"chunking_strategy": PLANTED},
        {"admission_batch": PLANTED * 10},
        {"chunk_size": 100, "overlap": 0, "secret_note": PLANTED},
    ],
    ids=["top_k", "question", "strategy", "batch", "chunk_size"],
)
def test_query_validation_errors_never_echo_input(env: Env, overrides: dict[str, Any]) -> None:
    response = env.ask(**overrides)

    detail = _assert_safe_422(response, PLANTED, "input", "ctx", "pydantic.dev")
    assert all(error["loc"][0] == "body" for error in detail)
    assert env.generation_calls == []


def test_malformed_json_returns_safe_422(env: Env) -> None:
    response = env.client.post(
        ASK_URL, content=b'{"question": "' + PLANTED.encode() + b'", broken', headers={"content-type": "application/json"}
    )

    _assert_safe_422(response, PLANTED, "broken")


def test_ingestion_validation_errors_never_echo_input(env: Env) -> None:
    response = env.upload(_pdf_bytes(), data={**VALID_METADATA, "document_name": PLANTED * 20})

    _assert_safe_422(response, PLANTED)


# --------------------------------------------------------------------------- #
# 14. Environment-variable configuration
# --------------------------------------------------------------------------- #


ENV_OVERRIDES = [
    ("MAX_UPLOAD_BYTES", "max_upload_bytes", 5 * MIB),
    ("UPLOAD_MULTIPART_OVERHEAD_BYTES", "upload_multipart_overhead_bytes", 2 * MIB),
    ("MAX_JSON_BODY_BYTES", "max_json_body_bytes", 32 * 1024),
    ("MAX_PDF_PAGES", "max_pdf_pages", 50),
    ("MAX_QUESTION_LENGTH", "max_question_length", 500),
    ("MAX_IDENTIFIER_LENGTH", "max_identifier_length", 40),
    ("MAX_TOP_K", "max_top_k", 10),
    ("MIN_CHUNK_SIZE", "min_chunk_size", 300),
    ("MAX_CHUNK_SIZE", "max_chunk_size", 2000),
    ("MAX_OVERLAP", "max_overlap", 500),
    ("MAX_DOCUMENT_NAME_LENGTH", "max_document_name_length", 120),
    ("MAX_REGULATION_VERSION_LENGTH", "max_regulation_version_length", 20),
    ("MAX_EFFECTIVE_DATE_LENGTH", "max_effective_date_length", 10),
    ("MAX_APPLICABILITY_VALUES", "max_applicability_values", 10),
    ("MAX_FORM_FIELDS", "max_form_fields", 60),
    ("MAX_FORM_PART_SIZE", "max_form_part_size", 8 * 1024),
]


def test_defaults_match_approved_limits() -> None:
    defaults = Settings()
    assert defaults.max_upload_bytes == 20 * MIB
    assert defaults.max_pdf_pages == 500
    assert defaults.max_json_body_bytes == 64 * 1024
    assert defaults.max_question_length == 2000
    assert defaults.max_identifier_length == 100
    assert defaults.max_top_k == 20
    assert (defaults.min_chunk_size, defaults.max_chunk_size, defaults.max_overlap) == (200, 4000, 1000)
    assert defaults.max_document_name_length == 200
    assert defaults.max_regulation_version_length == 50
    assert defaults.max_effective_date_length == 32
    assert defaults.max_applicability_values == 50
    assert (defaults.max_form_fields, defaults.max_form_part_size) == (120, 16 * 1024)


@pytest.mark.parametrize(("env_name", "attribute", "value"), ENV_OVERRIDES, ids=[e[0] for e in ENV_OVERRIDES])
def test_environment_variables_override_limits(
    monkeypatch: pytest.MonkeyPatch, env_name: str, attribute: str, value: int
) -> None:
    monkeypatch.setenv(env_name, f" {value} ")

    assert getattr(get_settings(), attribute) == value


def test_every_limit_has_a_tested_environment_variable() -> None:
    env_backed = {f.metadata["env"] for f in dataclasses.fields(Settings) if "env" in f.metadata}
    assert env_backed == {name for name, _, _ in ENV_OVERRIDES}


def test_blank_environment_value_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TOP_K", "  ")
    assert get_settings().max_top_k == 20


@pytest.mark.parametrize("value", ["abc", "1.5", "true", "20MB", "0", "-1"])
def test_invalid_environment_values_are_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", value)

    with pytest.raises(ValueError, match="MAX_UPLOAD_BYTES") as excinfo:
        get_settings()
    assert value not in str(excinfo.value) or value in {"0"}


@pytest.mark.parametrize(
    ("env_name", "value", "message"),
    [
        ("MIN_CHUNK_SIZE", "5000", "MIN_CHUNK_SIZE must not exceed MAX_CHUNK_SIZE"),
        ("MAX_CHUNK_SIZE", "900", "default chunk_size"),
        ("MAX_TOP_K", "4", "default top_k"),
        ("MAX_OVERLAP", "100", "default overlap"),
        ("MAX_EFFECTIVE_DATE_LENGTH", "9", "MAX_EFFECTIVE_DATE_LENGTH"),
    ],
)
def test_inconsistent_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch, env_name: str, value: str, message: str
) -> None:
    monkeypatch.setenv(env_name, value)

    with pytest.raises(ValueError, match=message):
        get_settings()


def test_overridden_settings_drive_the_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_JSON_BODY_BYTES", "200")
    configured = get_settings()

    async def echo(request: Request) -> JSONResponse:
        return JSONResponse({"bytes": len(await request.body())})

    small_app = Starlette(routes=[Route("/echo", echo, methods=["POST"])])
    small_app.add_middleware(
        RequestSizeLimitMiddleware,
        default_limit=BodyLimit(configured.max_json_body_bytes, "too big"),
    )
    client = TestClient(small_app)

    assert client.post("/echo", content=b"x" * 200).json() == {"bytes": 200}
    rejected = client.post("/echo", content=b"x" * 201)
    assert rejected.status_code == 413 and rejected.json() == {"detail": "too big"}
    streamed = client.post("/echo", content=_streamed(b"x" * 201, piece=50))
    assert streamed.status_code == 413


# --------------------------------------------------------------------------- #
# 15. Successful ingestion and Streamlit compatibility
# --------------------------------------------------------------------------- #


def test_successful_ingestion_is_unchanged(env: Env) -> None:
    response = env.upload(_pdf_bytes(pages=3))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ingested"
    assert body["verification_status"] == "pending"
    assert body["message"] == "Regulation ingested and stored as pending administrator verification."
    assert body["extraction_summary"]["total_pages"] == 3
    env.assert_no_temp_files_left()


def test_streamlit_question_path_is_not_limited_by_api_rules(env: Env) -> None:
    """Streamlit calls the workflow directly; API-only limits must not apply there."""
    result = workflow.answer_student_question(
        admission_batch=BATCH,
        programme=PROGRAMME,
        question="q" * 3000,
        db_path=env.db_path,
        top_k=50,
        chunk_size=100,
        overlap=0,
        chunking_strategy="fixed",
    )

    assert result["status"] == "insufficient_evidence"  # from the Gemini test double
    assert len(env.generation_calls) == 1


def test_streamlit_ingestion_path_is_not_limited_by_api_rules(env: Env, tmp_path: Path) -> None:
    pdf_path = tmp_path / "large_regulation.pdf"
    pdf_path.write_bytes(_pdf_bytes(pages=600, text=None))

    result = workflow.ingest_uploaded_regulation(
        pdf_path,
        {**VALID_METADATA, "document_name": "d" * 300, "effective_date": "1 August 2024"},
        db_path=env.db_path,
    )

    assert result["status"] == "ingested"
    assert result["extraction_summary"]["total_pages"] == 600


def test_openapi_documents_limits(env: Env) -> None:
    schema = env.client.get("/openapi.json").json()
    request_schema = schema["components"]["schemas"]["StudentQuestionRequest"]["properties"]
    assert request_schema["top_k"]["maximum"] == 20 and request_schema["top_k"]["minimum"] == 1
    assert request_schema["chunk_size"]["minimum"] == 200 and request_schema["chunk_size"]["maximum"] == 4000
    assert request_schema["question"]["maxLength"] == 2000
    assert "413" in schema["paths"][INGEST_URL]["post"]["responses"]
    assert env.client.get("/docs").status_code == 200
