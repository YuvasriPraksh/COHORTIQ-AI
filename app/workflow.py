"""End-to-end workflow orchestration for CohortIQ AI.

This module connects PDF extraction, database storage, chunking, retrieval,
Gemini answer generation, and citation validation into reusable admin and
student workflows. It enforces safety rules: no automatic approval, no invented
metadata, cohort/verification filtering through approved evidence, no Gemini
calls when retrieval has no evidence, and final citation validation.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.chunking import create_chunks
from app.citation_validator import validate_grounded_answer
from app.database import (
    get_applicable_regulations,
    get_document_pages,
    insert_document_pages,
    insert_regulation,
    update_regulation_verification_status,
)
from app.gemini_service import GeminiAnswerService, generate_grounded_answer
from app.models import GroundedAnswer
from app.pdf_processor import extract_text_from_pdf
from app.retrieval import retrieve_relevant_chunks

_REQUIRED_METADATA_FIELDS = (
    "document_name",
    "regulation_version",
    "effective_date",
    "applicable_batches",
    "applicable_programmes",
)


def _is_blank(value: Any) -> bool:
    """Return True when a required metadata value is missing/blank."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _normalize_applicability_input(value: Any, field_name: str) -> list[str]:
    """Validate and normalize applicability metadata into a non-empty string list."""
    if value is None:
        raise ValueError(f"Missing required metadata field: {field_name}")
    if isinstance(value, str):
        # Accept JSON array strings by delegating parsing to database validation later,
        # but reject blank strings as missing metadata.
        if not value.strip():
            raise ValueError(f"Missing required metadata field: {field_name}")
        return [value]  # pass through; database layer validates JSON-array strings
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value if str(item).strip()]
        if not items:
            raise ValueError(f"Missing required metadata field: {field_name}")
        return items
    raise ValueError(f"Invalid metadata field '{field_name}': expected a list of values.")


def _to_iso_date_string(value: Any) -> str:
    """Convert supported date values to an ISO-format string."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _build_extraction_summary(extraction_result: Mapping[str, Any]) -> dict[str, Any]:
    """Build a concise extraction summary for ingestion results."""
    pages = extraction_result.get("pages", []) or []
    page_summaries = []
    success_pages = 0
    needs_attention_pages = 0
    for page in pages:
        status = page.get("status")
        if status == "success":
            success_pages += 1
        else:
            needs_attention_pages += 1
        page_summaries.append(
            {
                "page_number": page.get("page_number"),
                "status": status,
            }
        )
    return {
        "filename": extraction_result.get("filename"),
        "total_pages": extraction_result.get("total_pages", len(pages)),
        "successful_pages": success_pages,
        "pages_needing_attention": needs_attention_pages,
        "pages": page_summaries,
    }


def _validate_admin_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize administrator-provided regulation metadata.

    Required metadata must be explicitly provided and is never invented.
    """
    if metadata is None:
        raise ValueError("Metadata is required.")

    missing = [field for field in _REQUIRED_METADATA_FIELDS if _is_blank(metadata.get(field))]
    # Applicability can be non-string containers; check presence/emptiness separately.
    for field in ("applicable_batches", "applicable_programmes"):
        if field in missing:
            continue
        value = metadata.get(field)
        if value is None:
            missing.append(field)
        elif isinstance(value, (list, tuple, set)) and len([v for v in value if str(v).strip()]) == 0:
            missing.append(field)
    if missing:
        # Preserve stable order and uniqueness.
        unique_missing = list(dict.fromkeys(missing))
        raise ValueError(
            "Missing or invalid required metadata: " + ", ".join(unique_missing)
        )

    normalized: dict[str, Any] = {
        "document_name": str(metadata.get("document_name")).strip(),
        "regulation_version": str(metadata.get("regulation_version")).strip(),
        "effective_date": _to_iso_date_string(metadata.get("effective_date")),
        "applicable_batches": _normalize_applicability_input(
            metadata.get("applicable_batches"), "applicable_batches"
        ),
        "applicable_programmes": _normalize_applicability_input(
            metadata.get("applicable_programmes"), "applicable_programmes"
        ),
    }
    # System/upload metadata: deterministic default is allowed (not regulation content).
    upload_date = metadata.get("upload_date")
    normalized["upload_date"] = (
        _to_iso_date_string(upload_date) if upload_date is not None else date.today().isoformat()
    )

    # Pass through optional fields only when explicitly provided.
    for optional_key in ("total_pages", "processing_status"):
        if optional_key in metadata:
            normalized[optional_key] = metadata.get(optional_key)
    return normalized


def ingest_uploaded_regulation(
    pdf_path: str | Path,
    metadata: Mapping[str, Any],
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Ingest an uploaded regulation PDF into the database as unverified evidence.

    Workflow: validate admin metadata, extract PDF text page-by-page, store
    regulation metadata and extracted pages in SQLite, and set verification
    status explicitly to ``pending``. Documents are never auto-approved.

    Args:
        pdf_path: Path to the uploaded PDF file.
        metadata: Administrator-provided regulation metadata.
        db_path: Optional SQLite database path override.

    Returns:
        A structured result containing status, regulation ID (when created),
        extraction summary, and error details on failure.
    """
    try:
        normalized_metadata = _validate_admin_metadata(metadata)
    except Exception as exc:
        return {
            "status": "error",
            "regulation_id": None,
            "extraction_summary": None,
            "message": f"Invalid regulation metadata: {exc}",
        }

    try:
        extraction_result = extract_text_from_pdf(pdf_path)
    except Exception as exc:
        return {
            "status": "error",
            "regulation_id": None,
            "extraction_summary": None,
            "message": f"PDF extraction failed: {exc}",
        }

    extraction_summary = _build_extraction_summary(extraction_result)
    regulation_record = dict(normalized_metadata)
    regulation_record["total_pages"] = extraction_result.get("total_pages", regulation_record.get("total_pages"))
    regulation_record["processing_status"] = regulation_record.get("processing_status") or "extracted"
    # Safety: never auto-approve on ingestion/extraction success.
    regulation_record["verification_status"] = "pending"

    regulation_id: int | None = None
    try:
        regulation_id = insert_regulation(regulation_record, db_path=db_path)
        pages = extraction_result.get("pages", []) or []
        insert_document_pages(regulation_id, pages, db_path=db_path)
    except Exception as exc:
        return {
            "status": "error",
            "regulation_id": regulation_id,
            "extraction_summary": extraction_summary,
            "message": f"Failed to store regulation data: {exc}",
        }

    return {
        "status": "ingested",
        "regulation_id": regulation_id,
        "verification_status": "pending",
        "extraction_summary": extraction_summary,
        "message": "Regulation ingested and stored as pending administrator verification.",
    }


def approve_regulation(
    regulation_id: int,
    db_path: str | Path | None = None,
    verification_status: str = "approved",
) -> dict[str, Any]:
    """Explicitly approve or set a verification status for a regulation.

    This function must be called as an explicit administrator action. It never
    runs during ingestion and does not auto-approve documents.

    Args:
        regulation_id: Regulation primary key.
        db_path: Optional SQLite database path override.
        verification_status: Explicit status to store (default: ``approved``).

    Returns:
        A structured result indicating success/failure.
    """
    if verification_status is None or not str(verification_status).strip():
        return {
            "status": "error",
            "regulation_id": regulation_id,
            "updated": False,
            "message": "An explicit verification_status value is required.",
        }

    try:
        updated = update_regulation_verification_status(
            regulation_id=regulation_id,
            verification_status=str(verification_status),
            db_path=db_path,
        )
    except Exception as exc:
        return {
            "status": "error",
            "regulation_id": regulation_id,
            "updated": False,
            "message": f"Failed to update regulation verification status: {exc}",
        }

    if not updated:
        return {
            "status": "not_found",
            "regulation_id": regulation_id,
            "updated": False,
            "message": f"Regulation {regulation_id} was not found.",
        }

    return {
        "status": "updated",
        "regulation_id": regulation_id,
        "updated": True,
        "verification_status": str(verification_status),
        "message": f"Regulation {regulation_id} verification status updated explicitly.",
    }


def _no_evidence_corpus(message: str) -> dict[str, Any]:
    """Return a structured no-evidence corpus result."""
    return {
        "status": "no_evidence",
        "message": message,
        "regulations": [],
        "chunks": [],
    }


def build_retrieval_corpus_for_cohort(
    admission_batch: str,
    programme: str,
    db_path: str | Path | None = None,
    *,
    chunking_strategy: str = "recursive",
    chunk_size: int = 1000,
    overlap: int = 200,
) -> dict[str, Any]:
    """Build a cohort-specific retrieval corpus from approved regulations only.

    Retrieves approved/applicable regulations for the cohort, loads their pages,
    generates chunks, and preserves source/applicability/verification metadata.

    Args:
        admission_batch: Student admission batch/cohort.
        programme: Student programme.
        db_path: Optional SQLite database path override.
        chunking_strategy: Chunking strategy passed to ``create_chunks``.
        chunk_size: Maximum chunk size.
        overlap: Chunk overlap.

    Returns:
        A structured corpus with status, matching regulations, and chunks. If no
        approved applicable regulation exists, returns a clear no-evidence result.
    """
    if admission_batch is None or not str(admission_batch).strip():
        return _no_evidence_corpus("Admission batch is required to build a cohort corpus.")
    if programme is None or not str(programme).strip():
        return _no_evidence_corpus("Programme is required to build a cohort corpus.")

    try:
        regulations = get_applicable_regulations(
            str(admission_batch), str(programme), db_path=db_path
        )
    except Exception as exc:
        return _no_evidence_corpus(f"Failed to retrieve applicable regulations: {exc}")

    if not regulations:
        return _no_evidence_corpus(
            "No approved regulations applicable to the supplied admission batch and programme were found."
        )

    corpus_chunks: list[dict[str, Any]] = []
    included_regulations: list[dict[str, Any]] = []
    for regulation in regulations:
        regulation_id = regulation.get("id")
        try:
            pages = get_document_pages(regulation_id, db_path=db_path)
        except Exception as exc:
            # Skip a regulation that cannot be loaded, but continue building corpus from others.
            included_regulations.append(
                {
                    **dict(regulation),
                    "page_load_error": str(exc),
                    "pages_loaded": 0,
                    "chunks_created": 0,
                }
            )
            continue

        try:
            chunks = create_chunks(
                pages=pages,
                regulation_metadata=regulation,
                chunking_strategy=chunking_strategy,
                chunk_size=chunk_size,
                overlap=overlap,
            )
        except Exception:
            chunks = []

        enriched_chunks: list[dict[str, Any]] = []
        for chunk in chunks:
            enriched = dict(chunk)
            # Preserve verification status explicitly in corpus chunks.
            enriched["verification_status"] = regulation.get("verification_status")
            # Provide snake_case applicability aliases for downstream components.
            enriched.setdefault("applicable_batches", regulation.get("applicable_batches"))
            enriched.setdefault("applicable_programmes", regulation.get("applicable_programmes"))
            enriched.setdefault("chunk_text", enriched.get("chunk text"))
            enriched_chunks.append(enriched)

        corpus_chunks.extend(enriched_chunks)
        included_regulations.append(
            {
                **dict(regulation),
                "pages_loaded": len(pages),
                "chunks_created": len(enriched_chunks),
            }
        )

    if not corpus_chunks:
        return {
            "status": "no_evidence",
            "message": (
                "Approved applicable regulations were found, but no retrievable text chunks "
                "could be built from their extracted pages."
            ),
            "regulations": included_regulations,
            "chunks": [],
        }

    return {
        "status": "ok",
        "message": f"Built retrieval corpus with {len(corpus_chunks)} chunk(s) from {len(regulations)} approved regulation(s).",
        "regulations": included_regulations,
        "chunks": corpus_chunks,
    }


def _grounded_answer_to_dict(answer: GroundedAnswer) -> dict[str, Any]:
    """Convert a GroundedAnswer to a plain dictionary."""
    return answer.model_dump()


def answer_student_question(
    admission_batch: str,
    programme: str,
    question: str,
    *,
    db_path: str | Path | None = None,
    top_k: int = 5,
    chunking_strategy: str = "recursive",
    chunk_size: int = 1000,
    overlap: int = 200,
    evidence_chunks: Sequence[Any] | None = None,
    gemini_service: GeminiAnswerService | Any | None = None,
    gemini_client: Any | None = None,
    gemini_settings: Any | None = None,
    gemini_model_name: str | None = None,
) -> dict[str, Any]:
    """Answer a student question using approved cohort-specific regulation evidence.

    The workflow validates inputs, builds an approved cohort corpus, retrieves
    relevant chunks, calls Gemini only when retrieval returns evidence, and then
    passes the generated ``GroundedAnswer`` through final citation validation.

    Args:
        admission_batch: Student admission batch/cohort.
        programme: Student programme.
        question: Student question.
        db_path: Optional SQLite database path override.
        top_k: Maximum number of retrieved chunks to send as evidence.
        chunking_strategy: Chunking strategy for corpus construction.
        chunk_size: Chunk size for corpus construction.
        overlap: Chunk overlap for corpus construction.
        evidence_chunks: Optional prebuilt corpus chunks (primarily for testing/
            controlled integration). When provided, corpus building is skipped.
        gemini_service: Optional Gemini service instance with a
            ``generate_grounded_answer(...)`` method.
        gemini_client: Optional Gemini client passed to the service.
        gemini_settings: Optional settings object for Gemini service.
        gemini_model_name: Optional Gemini model name override.

    Returns:
        A structured result containing the validated answer, citations,
        validation issues, retrieval details, and status information.
    """
    if question is None or not str(question).strip():
        answer = GroundedAnswer(
            answer="I cannot answer because the question is empty. Please provide a specific question.",
            status="insufficient_evidence",
            citations=[],
            limitations="Empty question provided.",
        )
        return {
            "status": "insufficient_evidence",
            "answer": _grounded_answer_to_dict(answer),
            "citations": [],
            "validation_issues": [],
            "retrieval": {"status": "no_evidence", "message": "Empty question.", "results": []},
            "corpus": None,
        }

    if admission_batch is None or not str(admission_batch).strip() or programme is None or not str(programme).strip():
        answer = GroundedAnswer(
            answer="I cannot answer because admission batch and programme are required for cohort-specific retrieval.",
            status="insufficient_evidence",
            citations=[],
            limitations="Missing admission batch or programme.",
        )
        return {
            "status": "insufficient_evidence",
            "answer": _grounded_answer_to_dict(answer),
            "citations": [],
            "validation_issues": [],
            "retrieval": {"status": "no_evidence", "message": "Missing cohort information.", "results": []},
            "corpus": None,
        }

    if evidence_chunks is None:
        corpus = build_retrieval_corpus_for_cohort(
            admission_batch=str(admission_batch),
            programme=str(programme),
            db_path=db_path,
            chunking_strategy=chunking_strategy,
            chunk_size=chunk_size,
            overlap=overlap,
        )
        if corpus.get("status") != "ok" or not corpus.get("chunks"):
            message = corpus.get("message") or "No applicable approved evidence was found."
            answer = GroundedAnswer(
                answer="I cannot provide a grounded answer because no applicable approved regulation evidence was found for this cohort and question.",
                status="insufficient_evidence",
                citations=[],
                limitations=message,
            )
            return {
                "status": "insufficient_evidence",
                "answer": _grounded_answer_to_dict(answer),
                "citations": [],
                "validation_issues": [],
                "retrieval": {
                    "status": "no_evidence",
                    "message": message,
                    "results": [],
                },
                "corpus": corpus,
            }
        chunks_for_retrieval = corpus.get("chunks", [])
    else:
        corpus = {
            "status": "ok",
            "message": "Using provided evidence chunks.",
            "regulations": [],
            "chunks": list(evidence_chunks),
        }
        chunks_for_retrieval = list(evidence_chunks)

    retrieval = retrieve_relevant_chunks(
        question=str(question),
        admission_batch=str(admission_batch),
        programme=str(programme),
        chunks=chunks_for_retrieval,
        top_k=top_k,
        approved_only=True,
    )

    if retrieval.get("status") != "ok" or not retrieval.get("results"):
        message = retrieval.get("message") or "No applicable approved evidence was found."
        answer = GroundedAnswer(
            answer="I cannot provide a grounded answer because no applicable approved regulation evidence was found for this cohort and question.",
            status="insufficient_evidence",
            citations=[],
            limitations=message,
        )
        return {
            "status": "insufficient_evidence",
            "answer": _grounded_answer_to_dict(answer),
            "citations": [],
            "validation_issues": [],
            "retrieval": retrieval,
            "corpus": corpus,
        }

    retrieved_evidence = retrieval.get("results", [])

    try:
        if gemini_service is not None and hasattr(gemini_service, "generate_grounded_answer"):
            generated_answer = gemini_service.generate_grounded_answer(
                question=str(question),
                admission_batch=str(admission_batch),
                programme=str(programme),
                evidence_chunks=retrieved_evidence,
            )
        else:
            generated_answer = generate_grounded_answer(
                question=str(question),
                admission_batch=str(admission_batch),
                programme=str(programme),
                evidence_chunks=retrieved_evidence,
                settings=gemini_settings,
                client=gemini_client,
                model_name=gemini_model_name,
            )
        if not isinstance(generated_answer, GroundedAnswer):
            raise TypeError("Gemini service returned an invalid answer type.")
    except ValueError as exc:
        generated_answer = GroundedAnswer(
            answer="I cannot provide a grounded answer because the answer generation service is not configured correctly.",
            status="insufficient_evidence",
            citations=[],
            limitations=str(exc),
        )
    except Exception as exc:
        generated_answer = GroundedAnswer(
            answer="I cannot provide a grounded answer because the answer generation service failed.",
            status="insufficient_evidence",
            citations=[],
            limitations=f"Gemini generation error: {exc}",
        )

    # Final safeguard: validate citations against the same original retrieved evidence.
    try:
        validated_answer, validation_issues = validate_grounded_answer(
            generated_answer, retrieved_evidence
        )
    except Exception as exc:
        validated_answer = GroundedAnswer(
            answer="I cannot provide a grounded answer because citation validation failed.",
            status="insufficient_evidence",
            citations=[],
            limitations=f"Citation validation error: {exc}",
        )
        validation_issues = [str(exc)]

    return {
        "status": validated_answer.status,
        "answer": _grounded_answer_to_dict(validated_answer),
        "citations": [citation.model_dump() for citation in validated_answer.citations],
        "validation_issues": validation_issues,
        "retrieval": retrieval,
        "corpus": corpus,
    }
