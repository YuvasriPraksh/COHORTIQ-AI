"""Text chunking utilities for CohortIQ AI.

This module converts extracted regulation page text into smaller searchable
chunks while preserving source metadata needed for citations and applicability.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

ChunkDict = dict[str, Any]
PageLike = Mapping[str, Any]

_STRATEGY_ALIASES = {
    "fixed": "fixed_size",
    "fixed_size": "fixed_size",
    "fixed-size": "fixed_size",
    "recursive": "recursive",
    "semantic": "semantic",
    "semantic_style": "semantic",
    "semantic-style": "semantic",
}


def _normalize_strategy(strategy: str) -> str:
    """Normalize a chunking strategy name to a supported internal value."""
    key = strategy.strip().lower().replace(" ", "_")
    normalized = _STRATEGY_ALIASES.get(key)
    if normalized is None:
        raise ValueError(
            "Unsupported chunking strategy. Use 'fixed_size', 'recursive', or 'semantic'."
        )
    return normalized


def _validate_chunk_params(chunk_size: int, overlap: int) -> None:
    """Validate chunk size and overlap configuration."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    if overlap < 0:
        raise ValueError("overlap must be 0 or greater")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")


def _clean_text(text: str | None) -> str:
    """Return text as a string without altering meaningful content."""
    if text is None:
        return ""
    return str(text)


def _dedupe_preserve_order(chunks: list[str]) -> list[str]:
    """Remove duplicate chunk texts while preserving original order."""
    seen: set[str] = set()
    unique_chunks: list[str] = []
    for chunk in chunks:
        if chunk in seen:
            continue
        seen.add(chunk)
        unique_chunks.append(chunk)
    return unique_chunks


def _apply_overlap(chunks: list[str], overlap: int) -> list[str]:
    """Prefix each chunk (except the first) with overlap text from the previous chunk."""
    if overlap <= 0 or len(chunks) <= 1:
        return chunks

    overlapped: list[str] = [chunks[0]]
    for index in range(1, len(chunks)):
        previous = overlapped[index - 1]
        prefix = previous[-overlap:] if overlap < len(previous) else previous
        combined = prefix + chunks[index]
        if combined == overlapped[-1]:
            combined = chunks[index]
        overlapped.append(combined)
    return _dedupe_preserve_order(overlapped)


def fixed_size_chunking(
    text: str, chunk_size: int = 1000, overlap: int = 200
) -> list[str]:
    """Split text into fixed-size character chunks with optional overlap.

    Args:
        text: Source text to split.
        chunk_size: Maximum number of characters per chunk.
        overlap: Number of overlapping characters between consecutive chunks.

    Returns:
        A list of chunk strings in source order. Returns an empty list for empty
        or whitespace-only text.
    """
    _validate_chunk_params(chunk_size, overlap)
    source_text = _clean_text(text)
    if not source_text.strip():
        return []

    step = chunk_size - overlap
    chunks: list[str] = []
    start = 0
    text_length = len(source_text)
    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunk = source_text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        if end >= text_length:
            break
        start += step

    return _dedupe_preserve_order(chunks)


def _split_by_separator(text: str, separator: str) -> list[str]:
    """Split text by a separator while keeping non-empty parts in order."""
    if separator == "":
        return list(text)
    parts = text.split(separator)
    return [part for part in parts if part != ""]


def _recursive_split_units(text: str, separators: list[str], chunk_size: int) -> list[str]:
    """Recursively split text into units that fit within ``chunk_size``."""
    if len(text) <= chunk_size:
        return [text]

    if not separators:
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    separator = separators[0]
    remaining_separators = separators[1:]

    if separator != "" and separator not in text:
        return _recursive_split_units(text, remaining_separators, chunk_size)

    parts = _split_by_separator(text, separator)
    if len(parts) <= 1:
        return _recursive_split_units(text, remaining_separators, chunk_size)

    units: list[str] = []
    for index, part in enumerate(parts):
        piece = part
        # Reattach separator (except after the last part) to preserve text structure.
        if separator != "" and index < len(parts) - 1:
            piece += separator
        if len(piece) <= chunk_size:
            units.append(piece)
        else:
            units.extend(_recursive_split_units(piece, remaining_separators, chunk_size))
    return [unit for unit in units if unit != ""]


def recursive_chunking(
    text: str, chunk_size: int = 1000, overlap: int = 200
) -> list[str]:
    """Split text recursively using paragraph/sentence/character boundaries.

    The strategy prefers larger, more meaningful boundaries first (paragraphs,
    then line/sentence boundaries, then words, then characters) and avoids
    breaking text unless a segment cannot fit within ``chunk_size``.

    Args:
        text: Source text to split.
        chunk_size: Maximum number of characters per chunk.
        overlap: Number of overlapping characters between consecutive chunks.

    Returns:
        A list of chunk strings in source order. Returns an empty list for empty
        or whitespace-only text.
    """
    _validate_chunk_params(chunk_size, overlap)
    source_text = _clean_text(text)
    if not source_text.strip():
        return []

    separators = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]
    units = _recursive_split_units(source_text, separators, chunk_size)

    chunks: list[str] = []
    current = ""
    for unit in units:
        if not unit:
            continue
        if not current:
            current = unit
            continue
        if len(current) + len(unit) <= chunk_size:
            current += unit
        else:
            if current.strip():
                chunks.append(current)
            current = unit
    if current.strip():
        chunks.append(current)

    # Safety fallback: ensure no chunk exceeds the configured size.
    bounded_chunks: list[str] = []
    for chunk in chunks:
        if len(chunk) <= chunk_size:
            bounded_chunks.append(chunk)
        else:
            bounded_chunks.extend(fixed_size_chunking(chunk, chunk_size=chunk_size, overlap=0))

    bounded_chunks = [chunk for chunk in bounded_chunks if chunk.strip()]
    bounded_chunks = _apply_overlap(bounded_chunks, overlap)
    return _dedupe_preserve_order(bounded_chunks)


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentence-like units using a lightweight regex heuristic."""
    stripped = text.strip()
    if not stripped:
        return []
    # Split after sentence-ending punctuation or paragraph breaks while keeping delimiters.
    parts = re.split(r"(?<=[.!?])\s+|\n+", stripped)
    sentences = [part.strip() for part in parts if part and part.strip()]
    if sentences:
        return sentences
    return [stripped]


def _tokenize_for_similarity(text: str) -> set[str]:
    """Tokenize text into a lowercase word set for lightweight similarity checks."""
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if token}


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    """Compute Jaccard similarity between two token sets."""
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def semantic_chunking(
    text: str, chunk_size: int = 1000, overlap: int = 0
) -> list[str]:
    """Group consecutive sentences using a lightweight local similarity baseline.

    This is a deterministic sentence-grouping strategy (not embedding-based
    semantic chunking and not an external API). It groups consecutive sentences
    when they are textually similar (token-overlap heuristic) and fit within the
    configured chunk size; otherwise it starts a new chunk.

    Limitation: without local embedding/NLP dependencies, this approximates
    semantic relatedness using lexical overlap rather than true semantic vectors.

    Args:
        text: Source text to split.
        chunk_size: Maximum number of characters per chunk.
        overlap: Number of overlapping characters between consecutive chunks.

    Returns:
        A list of chunk strings in source order. Returns an empty list for empty
        or whitespace-only text.
    """
    _validate_chunk_params(chunk_size, overlap)
    source_text = _clean_text(text)
    if not source_text.strip():
        return []

    sentences = _split_into_sentences(source_text)
    if not sentences:
        return []

    chunks: list[str] = []
    current_sentences: list[str] = [sentences[0]]
    current_text = sentences[0]
    current_tokens = _tokenize_for_similarity(sentences[0])

    for sentence in sentences[1:]:
        candidate_text = f"{current_text} {sentence}".strip()
        sentence_tokens = _tokenize_for_similarity(sentence)
        similarity = _jaccard_similarity(current_tokens, sentence_tokens)
        fits = len(candidate_text) <= chunk_size

        # Group consecutive sentences when they appear textually related and fit;
        # otherwise start a new chunk. This is a lightweight local similarity baseline.
        if fits and similarity >= 0.08:
            current_sentences.append(sentence)
            current_text = candidate_text
            current_tokens |= sentence_tokens
        else:
            if current_text.strip():
                chunks.append(current_text)
            if len(sentence) <= chunk_size:
                current_sentences = [sentence]
                current_text = sentence
                current_tokens = sentence_tokens
            else:
                # Long sentence fallback: preserve content via fixed-size splitting.
                split_parts = fixed_size_chunking(sentence, chunk_size=chunk_size, overlap=0)
                if split_parts:
                    chunks.extend(split_parts[:-1])
                    current_text = split_parts[-1]
                    current_sentences = [current_text]
                    current_tokens = _tokenize_for_similarity(current_text)
                else:
                    current_sentences = []
                    current_text = ""
                    current_tokens = set()

    if current_text.strip():
        chunks.append(current_text)

    bounded_chunks: list[str] = []
    for chunk in chunks:
        if len(chunk) <= chunk_size:
            bounded_chunks.append(chunk)
        else:
            bounded_chunks.extend(fixed_size_chunking(chunk, chunk_size=chunk_size, overlap=0))

    bounded_chunks = [chunk for chunk in bounded_chunks if chunk.strip()]
    bounded_chunks = _apply_overlap(bounded_chunks, overlap)
    return _dedupe_preserve_order(bounded_chunks)


def _get_page_text(page: PageLike) -> str:
    """Extract page text from supported page representations."""
    if "extracted_text" in page:
        return _clean_text(page.get("extracted_text"))
    return _clean_text(page.get("text"))


def _get_page_number(page: PageLike, fallback_index: int) -> int:
    """Return the original page number, falling back to a 1-based index."""
    value = page.get("page_number", fallback_index)
    try:
        page_number = int(value)
    except (TypeError, ValueError):
        page_number = fallback_index
    return page_number if page_number > 0 else fallback_index


def _build_chunk(
    *,
    chunk_id: str,
    regulation_id: Any,
    document_name: Any,
    regulation_version: Any,
    page_number: int,
    admission_batch_applicability: Any,
    programme_applicability: Any,
    chunking_strategy: str,
    chunk_text_value: str,
) -> ChunkDict:
    """Build a structured chunk dictionary with required metadata."""
    return {
        "chunk_id": chunk_id,
        "regulation_id": regulation_id,
        "document_name": document_name,
        "regulation_version": regulation_version,
        "page_number": page_number,
        "admission batch applicability": admission_batch_applicability,
        "programme applicability": programme_applicability,
        "chunking strategy": chunking_strategy,
        "chunk text": chunk_text_value,
    }


def _split_text_by_strategy(
    text: str, strategy: str, chunk_size: int, overlap: int
) -> list[str]:
    """Dispatch text splitting to the selected chunking strategy."""
    if strategy == "fixed_size":
        return fixed_size_chunking(text, chunk_size=chunk_size, overlap=overlap)
    if strategy == "recursive":
        return recursive_chunking(text, chunk_size=chunk_size, overlap=overlap)
    if strategy == "semantic":
        return semantic_chunking(text, chunk_size=chunk_size, overlap=overlap)
    raise ValueError(f"Unsupported normalized strategy: {strategy}")


def create_chunks(
    pages: Sequence[PageLike] | Iterable[PageLike],
    regulation_id: Any = None,
    document_name: Any = None,
    regulation_version: Any = None,
    admission_batch_applicability: Any = None,
    programme_applicability: Any = None,
    *,
    chunking_strategy: str = "recursive",
    chunk_size: int = 1000,
    overlap: int = 200,
    regulation_metadata: Mapping[str, Any] | None = None,
) -> list[ChunkDict]:
    """Create structured chunks from extracted regulation pages.

    Chunks are created per source page so page references are never lost. Each
    chunk includes the required source/applicability metadata and the selected
    chunking strategy label.

    Args:
        pages: Sequence of page-like mappings containing page text and page
            numbers (e.g. PDF/DB page records).
        regulation_id: Regulation identifier. May be provided via
            ``regulation_metadata`` instead.
        document_name: Source document name.
        regulation_version: Regulation version identifier.
        admission_batch_applicability: Applicable admission batches/cohorts.
        programme_applicability: Applicable programmes.
        chunking_strategy: One of ``fixed_size``, ``recursive``, or ``semantic``
            (aliases accepted).
        chunk_size: Maximum characters per chunk.
        overlap: Overlap size in characters between consecutive chunks.
        regulation_metadata: Optional metadata mapping (e.g. DB regulation row)
            used to fill missing metadata fields.

    Returns:
        A list of structured chunk dictionaries. Empty or whitespace-only pages
        produce no chunks.
    """
    strategy = _normalize_strategy(chunking_strategy)
    metadata = regulation_metadata or {}

    resolved_regulation_id = (
        metadata.get("id", metadata.get("regulation_id", regulation_id))
        if regulation_id is None or regulation_id == metadata.get("regulation_id")
        else regulation_id
    )
    if resolved_regulation_id is None:
        resolved_regulation_id = metadata.get("id", metadata.get("regulation_id"))

    resolved_document_name = (
        document_name if document_name is not None else metadata.get("document_name")
    )
    resolved_regulation_version = (
        regulation_version
        if regulation_version is not None
        else metadata.get("regulation_version")
    )
    resolved_batches = (
        admission_batch_applicability
        if admission_batch_applicability is not None
        else metadata.get(
            "admission_batch_applicability",
            metadata.get("applicable_batches", metadata.get("admission batch applicability")),
        )
    )
    resolved_programmes = (
        programme_applicability
        if programme_applicability is not None
        else metadata.get(
            "programme_applicability",
            metadata.get("applicable_programmes", metadata.get("programme applicability")),
        )
    )

    all_chunks: list[ChunkDict] = []
    global_index = 0

    for fallback_index, page in enumerate(pages, start=1):
        page_number = _get_page_number(page, fallback_index)
        page_text = _get_page_text(page)
        if not page_text.strip():
            continue

        split_chunks = _split_text_by_strategy(
            page_text, strategy=strategy, chunk_size=chunk_size, overlap=overlap
        )
        for chunk_text_value in split_chunks:
            if not chunk_text_value or not str(chunk_text_value).strip():
                continue
            global_index += 1
            chunk_id = f"{resolved_regulation_id}-p{page_number}-c{global_index}"
            chunk_record = _build_chunk(
                chunk_id=chunk_id,
                regulation_id=resolved_regulation_id,
                document_name=resolved_document_name,
                regulation_version=resolved_regulation_version,
                page_number=page_number,
                admission_batch_applicability=resolved_batches,
                programme_applicability=resolved_programmes,
                chunking_strategy=strategy,
                chunk_text_value=str(chunk_text_value),
            )
            # Avoid duplicate chunks where possible (identical text and source page).
            if all_chunks:
                previous = all_chunks[-1]
                if (
                    previous["page_number"] == chunk_record["page_number"]
                    and previous["chunk text"] == chunk_record["chunk text"]
                ):
                    global_index -= 1
                    continue
            all_chunks.append(chunk_record)

    return all_chunks


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """Backward-compatible helper that splits text using fixed-size chunking."""
    return fixed_size_chunking(text, chunk_size=chunk_size, overlap=overlap)

