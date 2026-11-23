"""Retrieval utilities for CohortIQ AI.

This module provides cohort-aware BM25 keyword retrieval over structured
regulation chunks while preserving source and applicability metadata.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Mapping, Sequence

from rank_bm25 import BM25Okapi

APPROVED_VERIFICATION_STATUSES = {
    "approved",
    "verified",
    "administrator_verified",
    "administrator_approved",
    "verified_and_approved",
}

_TOKEN_PATTERN = re.compile(
    r"[A-Za-z0-9]+(?:[./\-][A-Za-z0-9]+)*(?:\([A-Za-z0-9]+\))?"
)


def tokenize_text(text: str | None) -> list[str]:
    """Tokenize text for BM25 retrieval.

    The tokenizer lowercases text, normalizes punctuation by extracting token
    spans, and preserves meaningful academic terms, numbers, and clause
    references (for example ``4.2.1`` or ``10(a)``).

    Args:
        text: Input text to tokenize.

    Returns:
        A list of normalized tokens in original order.
    """
    if text is None:
        return []
    normalized = str(text).lower()
    return _TOKEN_PATTERN.findall(normalized)


def _to_string_list(value: Any) -> list[str]:
    """Convert an applicability/metadata value into a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if isinstance(value, set):
        return [str(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [stripped]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        if parsed is None:
            return []
        return [str(parsed)]
    return [str(value)]


def _is_approved_verification_status(status: Any) -> bool:
    """Return True when a status indicates an approved/verified regulation."""
    if status is None:
        return False
    return str(status).strip().lower() in APPROVED_VERIFICATION_STATUSES


def _get_first_present(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    """Return the first present (even if None) value for any key in ``keys``."""
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def _normalize_chunk_record(chunk: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalize a chunk-like record to standardized snake_case metadata.

    Returns ``None`` for records that cannot be interpreted as text chunks or
    that have empty chunk text.
    """
    chunk_text = _get_first_present(
        chunk, ("chunk_text", "chunk text", "text", "extracted_text")
    )
    if chunk_text is None:
        return None
    chunk_text_str = str(chunk_text)
    if not chunk_text_str.strip():
        return None

    applicable_batches = _to_string_list(
        _get_first_present(
            chunk,
            (
                "applicable_batches",
                "admission_batch_applicability",
                "admission batch applicability",
            ),
        )
    )
    applicable_programmes = _to_string_list(
        _get_first_present(
            chunk,
            (
                "applicable_programmes",
                "programme_applicability",
                "programme applicability",
            ),
        )
    )

    page_number = _get_first_present(chunk, ("page_number", "page number"))
    try:
        page_number_value = int(page_number) if page_number is not None else None
    except (TypeError, ValueError):
        page_number_value = None

    normalized = {
        "chunk_id": _get_first_present(chunk, ("chunk_id", "id")),
        "regulation_id": _get_first_present(chunk, ("regulation_id", "regulation id")),
        "document_name": _get_first_present(chunk, ("document_name", "document name")),
        "regulation_version": _get_first_present(
            chunk, ("regulation_version", "regulation version")
        ),
        "page_number": page_number_value,
        "applicable_batches": applicable_batches,
        "applicable_programmes": applicable_programmes,
        "chunking_strategy": _get_first_present(
            chunk, ("chunking_strategy", "chunking strategy")
        ),
        "chunk_text": chunk_text_str,
        "verification_status": _get_first_present(
            chunk, ("verification_status", "verification status")
        ),
    }
    return normalized


def _expand_document_record(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand an approved/document record into normalized chunk-like records.

    Supports records that already contain chunk text, records with a ``pages``
    list, or records with chunk collections under common keys.
    """
    # Already chunk-like
    normalized_direct = _normalize_chunk_record(record)
    if normalized_direct is not None and _get_first_present(record, ("chunk_text", "chunk text")) is not None:
        return [normalized_direct]

    base_metadata = {
        "regulation_id": _get_first_present(record, ("regulation_id", "id")),
        "document_name": _get_first_present(record, ("document_name", "name")),
        "regulation_version": _get_first_present(record, ("regulation_version", "version")),
        "applicable_batches": _to_string_list(
            _get_first_present(record, ("applicable_batches", "admission_batch_applicability"))
        ),
        "applicable_programmes": _to_string_list(
            _get_first_present(
                record, ("applicable_programmes", "programme_applicability")
            )
        ),
        "chunking_strategy": _get_first_present(record, ("chunking_strategy",)),
        "verification_status": _get_first_present(record, ("verification_status",)),
    }

    chunks: list[dict[str, Any]] = []

    # Nested chunk collections
    for key in ("chunks", "chunk_records"):
        nested = record.get(key)
        if isinstance(nested, list):
            for item in nested:
                if isinstance(item, Mapping):
                    merged = {**base_metadata, **dict(item)}
                    normalized = _normalize_chunk_record(merged)
                    if normalized is not None:
                        chunks.append(normalized)
            if chunks:
                return chunks

    # Page/document records (e.g. DB regulation joined with pages)
    pages = record.get("pages")
    if isinstance(pages, list):
        for index, page in enumerate(pages, start=1):
            if not isinstance(page, Mapping):
                continue
            merged = {**base_metadata, **dict(page)}
            if merged.get("chunk_id") is None:
                reg_id = merged.get("regulation_id")
                page_no = merged.get("page_number", index)
                merged["chunk_id"] = f"{reg_id}-p{page_no}-r{index}"
            normalized = _normalize_chunk_record(merged)
            if normalized is not None:
                chunks.append(normalized)
        return chunks

    # Single page-like record without explicit chunk_text key may still be extractable
    if normalized_direct is not None:
        # Fill in base metadata if missing
        for key, value in base_metadata.items():
            if normalized_direct.get(key) in (None, [], "") and value not in (None, [], ""):
                normalized_direct[key] = value
        return [normalized_direct]

    return []


def _normalize_input_items(items: Sequence[Any] | Iterable[Any] | None) -> list[dict[str, Any]]:
    """Normalize input chunks or approved document records into chunk records."""
    if items is None:
        return []
    normalized_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        # Prefer direct chunk normalization when chunk text is explicit.
        if _get_first_present(item, ("chunk_text", "chunk text")) is not None:
            normalized = _normalize_chunk_record(item)
            if normalized is not None:
                normalized_items.append(normalized)
            continue
        # Otherwise attempt to expand document/page records.
        expanded = _expand_document_record(item)
        if expanded:
            normalized_items.extend(expanded)
            continue
        # Fallback for page-like records using text/extracted_text.
        normalized = _normalize_chunk_record(item)
        if normalized is not None:
            normalized_items.append(normalized)
    return normalized_items


def build_bm25_index(chunks: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]]):
    """Build a BM25 index from structured document chunks.

    Args:
        chunks: Chunk or document-record mappings. Records are normalized to
            snake_case chunk metadata and empty-text chunks are excluded.

    Returns:
        A dictionary containing the BM25 model, normalized chunks in corpus
        order, and tokenized corpus. Returns ``None`` when no indexable chunks
        are available.
    """
    normalized_chunks = _normalize_input_items(chunks)
    if not normalized_chunks:
        return None

    tokenized_corpus = [tokenize_text(chunk["chunk_text"]) for chunk in normalized_chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    return {
        "bm25": bm25,
        "chunks": normalized_chunks,
        "tokenized_corpus": tokenized_corpus,
    }


def _matches_cohort(chunk: Mapping[str, Any], admission_batch: str, programme: str) -> bool:
    """Check whether a chunk's applicability matches the supplied cohort."""
    batches = _to_string_list(chunk.get("applicable_batches"))
    programmes = _to_string_list(chunk.get("applicable_programmes"))
    return str(admission_batch) in batches and str(programme) in programmes


def _filter_chunks_for_cohort(
    chunks: Sequence[Mapping[str, Any]],
    admission_batch: str,
    programme: str,
    *,
    approved_only: bool = True,
) -> tuple[list[dict[str, Any]], bool]:
    """Filter normalized chunks by verification status and cohort applicability.

    Returns:
        A tuple of ``(matching_chunks, has_approved_cohort_documents)`` where the
        second value indicates whether any approved/verified document matched the
        cohort (even if text chunks were empty/excluded earlier).
    """
    has_approved_cohort_documents = False
    matching: list[dict[str, Any]] = []

    for chunk in chunks:
        verification_status = chunk.get("verification_status")
        is_approved = _is_approved_verification_status(verification_status)
        if approved_only and not is_approved:
            continue
        if not _matches_cohort(chunk, admission_batch, programme):
            continue
        has_approved_cohort_documents = True
        matching.append(dict(chunk))
    return matching, has_approved_cohort_documents


def _format_result(
    chunk: Mapping[str, Any], admission_batch: str, programme: str, score: float
) -> dict[str, Any]:
    """Format a ranked chunk into the required retrieval result structure."""
    return {
        "chunk_id": chunk.get("chunk_id"),
        "chunk_text": chunk.get("chunk_text"),
        "regulation_id": chunk.get("regulation_id"),
        "document_name": chunk.get("document_name"),
        "regulation_version": chunk.get("regulation_version"),
        "page_number": chunk.get("page_number"),
        "admission_batch": str(admission_batch),
        "programme": str(programme),
        "retrieval_score": float(score),
    }


def _no_evidence_result(message: str) -> dict[str, Any]:
    """Return a clear structured no-evidence retrieval result."""
    return {
        "results": [],
        "status": "no_evidence",
        "message": message,
    }


def retrieve_relevant_chunks(
    question: str,
    admission_batch: str,
    programme: str,
    chunks: Sequence[Any] | Iterable[Any] | None = None,
    top_k: int = 5,
    *,
    approved_only: bool = True,
) -> dict[str, Any]:
    """Retrieve top-k relevant chunks for a cohort-aware question using BM25.

    Cohort filtering is applied before BM25 ranking. Only chunks belonging to
    administrator-approved/verified regulations whose applicability includes
    both the supplied admission batch and programme are considered. If multiple
    approved regulation versions match, all relevant candidates are eligible for
    retrieval; the function does not automatically select the newest version.

    Args:
        question: User's question.
        admission_batch: Student admission batch/cohort identifier.
        programme: Student programme identifier.
        chunks: Available structured chunks or approved document records.
        top_k: Maximum number of ranked results to return.
        approved_only: Whether to restrict retrieval to approved/verified
            regulations (default: True).

    Returns:
        A structured dictionary with ``results``, ``status``, and ``message``.
        Each result contains ``chunk_id``, ``chunk_text``, ``regulation_id``,
        ``document_name``, ``regulation_version``, ``page_number``,
        ``admission_batch``, ``programme``, and ``retrieval_score``. If there is
        no evidence (empty query, no chunks, no approved/applicable matches), a
        clear no-evidence result is returned.
    """
    if top_k <= 0:
        return _no_evidence_result("top_k must be greater than 0 to retrieve results.")

    if question is None or not str(question).strip():
        return _no_evidence_result(
            "No evidence could be retrieved because the question is empty."
        )

    normalized_chunks = _normalize_input_items(chunks)
    if not normalized_chunks:
        return _no_evidence_result(
            "No evidence could be retrieved because no document chunks are available."
        )

    filtered_chunks, has_approved_cohort_documents = _filter_chunks_for_cohort(
        normalized_chunks,
        admission_batch=admission_batch,
        programme=programme,
        approved_only=approved_only,
    )

    if not filtered_chunks:
        if has_approved_cohort_documents:
            return _no_evidence_result(
                "No evidence could be retrieved because matching approved documents "
                "do not contain retrievable text chunks."
            )
        return _no_evidence_result(
            "No applicable approved regulations were found for the supplied "
            "admission batch and programme."
        )

    index = build_bm25_index(filtered_chunks)
    if index is None:
        return _no_evidence_result(
            "No evidence could be retrieved because matching chunks could not be indexed."
        )

    query_tokens = tokenize_text(question)
    if not query_tokens:
        return _no_evidence_result(
            "No evidence could be retrieved because the question did not produce searchable tokens."
        )

    bm25: BM25Okapi = index["bm25"]
    ranked_chunks: list[dict[str, Any]] = index["chunks"]
    scores = bm25.get_scores(query_tokens)

    scored_results = [
        _format_result(chunk, admission_batch, programme, float(score))
        for chunk, score in zip(ranked_chunks, scores)
    ]
    scored_results.sort(key=lambda item: item["retrieval_score"], reverse=True)
    top_results = scored_results[:top_k]

    return {
        "results": top_results,
        "status": "ok",
        "message": f"Retrieved {len(top_results)} relevant chunk(s).",
    }

