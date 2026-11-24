"""Tests for the backend query service delegation layer."""

from __future__ import annotations

from unittest.mock import sentinel

from pytest import MonkeyPatch

from backend.app.services import query_service


def test_build_cohort_retrieval_corpus_delegates_to_workflow(
    monkeypatch: MonkeyPatch,
) -> None:
    """Corpus service should delegate to app.workflow with preserved args/return."""
    calls: dict[str, object] = {}

    def fake_build_retrieval_corpus_for_cohort(
        *,
        admission_batch,
        programme,
        db_path,
        chunking_strategy,
        chunk_size,
        overlap,
    ):
        calls.update(
            {
                "admission_batch": admission_batch,
                "programme": programme,
                "db_path": db_path,
                "chunking_strategy": chunking_strategy,
                "chunk_size": chunk_size,
                "overlap": overlap,
            }
        )
        return {"status": "ok", "chunks": [sentinel.chunk]}

    monkeypatch.setattr(
        "app.workflow.build_retrieval_corpus_for_cohort",
        fake_build_retrieval_corpus_for_cohort,
    )

    result = query_service.build_cohort_retrieval_corpus(
        admission_batch="2024",
        programme="BSc CS",
        db_path="C:/tmp/test.db",
        chunking_strategy="recursive",
        chunk_size=900,
        overlap=150,
    )

    assert result == {"status": "ok", "chunks": [sentinel.chunk]}
    assert calls == {
        "admission_batch": "2024",
        "programme": "BSc CS",
        "db_path": "C:/tmp/test.db",
        "chunking_strategy": "recursive",
        "chunk_size": 900,
        "overlap": 150,
    }


def test_answer_student_regulation_question_delegates_to_workflow(
    monkeypatch: MonkeyPatch,
) -> None:
    """QA service should delegate to app.workflow preserving pipeline args/return."""
    calls: dict[str, object] = {}

    def fake_answer_student_question(
        *,
        admission_batch,
        programme,
        question,
        db_path,
        top_k,
        chunking_strategy,
        chunk_size,
        overlap,
        evidence_chunks,
        gemini_service,
        gemini_client,
        gemini_settings,
        gemini_model_name,
    ):
        calls.update(
            {
                "admission_batch": admission_batch,
                "programme": programme,
                "question": question,
                "db_path": db_path,
                "top_k": top_k,
                "chunking_strategy": chunking_strategy,
                "chunk_size": chunk_size,
                "overlap": overlap,
                "evidence_chunks": evidence_chunks,
                "gemini_service": gemini_service,
                "gemini_client": gemini_client,
                "gemini_settings": gemini_settings,
                "gemini_model_name": gemini_model_name,
            }
        )
        return {"status": "answered", "answer": {"answer": "ok"}}

    monkeypatch.setattr("app.workflow.answer_student_question", fake_answer_student_question)

    provided_evidence = [{"chunk_id": "c1"}]
    result = query_service.answer_student_regulation_question(
        admission_batch="2024",
        programme="BSc CS",
        question="What is the attendance rule?",
        db_path="C:/tmp/test.db",
        top_k=7,
        chunking_strategy="fixed_size",
        chunk_size=800,
        overlap=100,
        evidence_chunks=provided_evidence,
        gemini_service=sentinel.service,
        gemini_client=sentinel.client,
        gemini_settings=sentinel.settings,
        gemini_model_name="test-model",
    )

    assert result == {"status": "answered", "answer": {"answer": "ok"}}
    assert calls == {
        "admission_batch": "2024",
        "programme": "BSc CS",
        "question": "What is the attendance rule?",
        "db_path": "C:/tmp/test.db",
        "top_k": 7,
        "chunking_strategy": "fixed_size",
        "chunk_size": 800,
        "overlap": 100,
        "evidence_chunks": provided_evidence,
        "gemini_service": sentinel.service,
        "gemini_client": sentinel.client,
        "gemini_settings": sentinel.settings,
        "gemini_model_name": "test-model",
    }
