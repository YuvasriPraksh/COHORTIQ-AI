"""Citation validation utilities for CohortIQ AI.

This module validates grounded-answer citations against the original retrieved
evidence. It never trusts model-generated metadata, restores citation fields from
evidence, rejects fabricated or inconsistent citations, and downgrades answers
that lack valid supporting citations to ``insufficient_evidence``.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from app.models import GroundedAnswer, GroundedCitation


def _get_first_present(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    """Return the first present mapping value for the given keys."""
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def _normalize_evidence_chunks(
    evidence_chunks: Sequence[Any] | Iterable[Any] | None,
) -> list[dict[str, Any]]:
    """Normalize original retrieved evidence into comparable chunk records."""
    if evidence_chunks is None:
        return []

    normalized: list[dict[str, Any]] = []
    for item in evidence_chunks:
        if not isinstance(item, Mapping):
            continue

        chunk_text = _get_first_present(
            item, ("chunk_text", "chunk text", "text", "extracted_text")
        )
        if chunk_text is None:
            continue
        chunk_text_str = str(chunk_text)
        if not chunk_text_str.strip():
            continue

        chunk_id_value = _get_first_present(item, ("chunk_id", "id"))
        if chunk_id_value is None or not str(chunk_id_value).strip():
            continue
        chunk_id = str(chunk_id_value)

        page_number = _get_first_present(item, ("page_number", "page number"))
        try:
            page_number_value = int(page_number) if page_number is not None else None
        except (TypeError, ValueError):
            page_number_value = None

        normalized.append(
            {
                "chunk_id": chunk_id,
                "document_name": _get_first_present(
                    item, ("document_name", "document name", "name")
                ),
                "regulation_version": _get_first_present(
                    item, ("regulation_version", "regulation version", "version")
                ),
                "page_number": page_number_value,
                "chunk_text": chunk_text_str,
            }
        )
    return normalized


def _evidence_lookup(evidence_chunks: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index normalized evidence by chunk_id."""
    return {str(chunk["chunk_id"]): dict(chunk) for chunk in evidence_chunks}


def _normalize_for_match(text: str) -> str:
    """Normalize text for robust supporting-text matching."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _supporting_text_matches_evidence(supporting_text: Any, chunk_text: str) -> bool:
    """Return True if supporting text can be matched to the cited evidence chunk."""
    if not isinstance(supporting_text, str):
        return False
    candidate = supporting_text.strip()
    if not candidate:
        return False

    # Direct containment is the strongest signal.
    if candidate in chunk_text:
        return True

    normalized_candidate = _normalize_for_match(candidate)
    normalized_chunk = _normalize_for_match(chunk_text)
    if not normalized_candidate or not normalized_chunk:
        return False
    return normalized_candidate in normalized_chunk


def _has_invalid_provided_metadata(citation: Mapping[str, Any], evidence: Mapping[str, Any]) -> tuple[bool, str | None]:
    """Detect invalid citation metadata formats relative to evidence.

    Citation metadata from the model is never trusted. For citations that are
    otherwise valid (known chunk_id and supporting text matched to evidence),
    metadata is restored from original evidence. This check only rejects
    malformed provided values or unusable source metadata in the evidence record.
    """
    evidence_doc = evidence.get("document_name")
    evidence_version = evidence.get("regulation_version")
    evidence_page = evidence.get("page_number")

    provided_doc = citation.get("document_name")
    if provided_doc is not None and str(provided_doc).strip() == "":
        return True, "missing or invalid source metadata"

    provided_version = citation.get("regulation_version")
    if provided_version is not None and str(provided_version).strip() == "":
        return True, "missing or invalid source metadata"

    if "page_number" in citation and citation.get("page_number") is not None:
        provided_page = citation.get("page_number")
        try:
            int(provided_page)
        except (TypeError, ValueError):
            return True, "missing or invalid source metadata"
        if evidence_page is not None:
            try:
                int(evidence_page)
            except (TypeError, ValueError):
                return True, "invalid page_number metadata"

    # Evidence must provide usable source identity when available.
    if evidence_doc is not None and str(evidence_doc).strip() == "":
        return True, "missing or invalid source metadata"
    if evidence_version is not None and str(evidence_version).strip() == "":
        return True, "missing or invalid source metadata"

    return False, None


def _citation_to_mapping(citation: Any) -> Mapping[str, Any] | None:
    """Convert a citation object to a mapping for validation."""
    if isinstance(citation, GroundedCitation):
        return citation.model_dump()
    if isinstance(citation, Mapping):
        return citation
    # Pydantic models or objects with dict-like export.
    if hasattr(citation, "model_dump"):
        try:
            dumped = citation.model_dump()
            if isinstance(dumped, Mapping):
                return dumped
        except Exception:
            return None
    return None


def _append_limitation(existing: str | None, message: str) -> str:
    """Append a clear limitation message without duplicating text."""
    if not existing or not existing.strip():
        return message
    if message in existing:
        return existing
    return f"{existing.rstrip()} {message}"


def _downgrade_to_insufficient(
    answer: GroundedAnswer, limitation: str, default_answer: str | None = None
) -> GroundedAnswer:
    """Return a copy downgraded to insufficient_evidence with explanation."""
    updated_answer = answer.answer
    if default_answer:
        updated_answer = default_answer
    elif answer.status != "insufficient_evidence":
        updated_answer = (
            "The available retrieved evidence is insufficient to provide a fully grounded answer "
            "with valid supporting citations."
        )
    return answer.model_copy(
        update={
            "answer": updated_answer,
            "status": "insufficient_evidence",
            "citations": [],
            "limitations": _append_limitation(answer.limitations, limitation),
        }
    )


def validate_grounded_answer(
    answer: GroundedAnswer, evidence_chunks: Sequence[Any] | Iterable[Any] | None
) -> tuple[GroundedAnswer, list[str]]:
    """Validate and normalize a ``GroundedAnswer`` against original evidence.

    Every citation is validated using ``chunk_id`` as the primary identifier.
    Citation metadata is restored from original evidence (never trusted from the
    model). Citations with unknown chunk IDs, malformed/invalid metadata,
    fabricated or unmatched supporting text, or inconsistent source/page details
    are rejected. Duplicate citations are removed.

    If an answer that requires supporting citations has no valid citations after
    validation, its status is downgraded to ``insufficient_evidence`` with a
    clear limitation. This function does not invent replacement citations or
    regulatory information.

    Args:
        answer: The grounded answer to validate.
        evidence_chunks: Original retrieved evidence chunks.

    Returns:
        A tuple of ``(validated_answer, issues)`` where ``validated_answer`` is
        a Pydantic ``GroundedAnswer`` compatible with the existing model and
        ``issues`` lists validation problems found.
    """
    if not isinstance(answer, GroundedAnswer):
        raise TypeError("answer must be a GroundedAnswer instance")

    normalized_evidence = _normalize_evidence_chunks(evidence_chunks)
    lookup = _evidence_lookup(normalized_evidence)
    issues: list[str] = []

    raw_citations = answer.citations or []
    if not raw_citations:
        if answer.status in {"answered", "conflicting_evidence"}:
            return (
                _downgrade_to_insufficient(
                    answer,
                    "No valid supporting citations were provided for the answer.",
                ),
                ["No citations provided for a grounded answer."],
            )
        # Insufficient evidence responses may legitimately have no citations.
        limitation = answer.limitations
        if not normalized_evidence and not limitation:
            limitation = "No original retrieved evidence was provided for citation validation."
        return (answer.model_copy(update={"limitations": limitation}), issues)

    if not normalized_evidence:
        issues.append("No original retrieved evidence was provided for citation validation.")
        return (
            _downgrade_to_insufficient(
                answer,
                "No original retrieved evidence was available to validate citations.",
            ),
            issues,
        )

    valid_citations: list[GroundedCitation] = []
    seen_chunk_ids: set[str] = set()

    for citation in raw_citations:
        citation_map = _citation_to_mapping(citation)
        if citation_map is None:
            issues.append("Rejected malformed citation entry.")
            continue

        chunk_id_value = citation_map.get("chunk_id")
        if chunk_id_value is None or not str(chunk_id_value).strip():
            issues.append("Rejected citation with missing chunk_id.")
            continue
        chunk_id = str(chunk_id_value)

        if chunk_id in seen_chunk_ids:
            issues.append(f"Removed duplicate citation for chunk_id '{chunk_id}'.")
            continue

        evidence = lookup.get(chunk_id)
        if evidence is None:
            issues.append(f"Rejected citation referencing unknown chunk_id '{chunk_id}'.")
            continue

        supporting_text = citation_map.get("relevant_supporting_text")
        if not _supporting_text_matches_evidence(supporting_text, str(evidence.get("chunk_text", ""))):
            issues.append(
                f"Rejected citation for chunk_id '{chunk_id}' because supporting text could not be matched to evidence."
            )
            continue

        has_invalid_metadata, metadata_issue = _has_invalid_provided_metadata(citation_map, evidence)
        if has_invalid_metadata:
            issues.append(
                f"Rejected citation for chunk_id '{chunk_id}' due to {metadata_issue}."
            )
            continue

        # Never trust Gemini metadata: restore citation fields from original evidence.
        restored_citation = GroundedCitation(
            document_name=(
                None if evidence.get("document_name") is None else str(evidence.get("document_name"))
            ),
            regulation_version=(
                None
                if evidence.get("regulation_version") is None
                else str(evidence.get("regulation_version"))
            ),
            page_number=evidence.get("page_number"),
            chunk_id=chunk_id,
            relevant_supporting_text=str(supporting_text).strip(),
        )
        valid_citations.append(restored_citation)
        seen_chunk_ids.add(chunk_id)

    if not valid_citations:
        limitation = "Citation validation failed: no valid supporting citations matched the original retrieved evidence."
        if issues:
            limitation = f"{limitation} {' '.join(issues)}"
        return (_downgrade_to_insufficient(answer, limitation), issues)

    updated_limitations = answer.limitations
    # For insufficient evidence, keep status but record any citation issues found.
    if issues:
        issue_summary = " ".join(issues)
        updated_limitations = _append_limitation(updated_limitations, issue_summary)

    # Conflicting evidence may remain conflicting when valid citations support it.
    updated_status = answer.status
    if updated_status == "answered" and not valid_citations:
        updated_status = "insufficient_evidence"

    return (
        answer.model_copy(
            update={
                "status": updated_status,
                "citations": valid_citations,
                "limitations": updated_limitations,
            }
        ),
        issues,
    )


def validate_citations(response: str | GroundedAnswer, sources: list[Any]) -> bool:
    """Compatibility helper for citation validation.

    Args:
        response: A ``GroundedAnswer`` instance or raw response text.
        sources: Original retrieved evidence chunks.

    Returns:
        ``True`` if the response is a ``GroundedAnswer`` that remains grounded
        with valid supporting citations after validation; otherwise ``False``.
    """
    if not isinstance(response, GroundedAnswer):
        return False
    validated, issues = validate_grounded_answer(response, sources)
    return validated.status in {"answered", "conflicting_evidence"} and bool(validated.citations) and not issues

