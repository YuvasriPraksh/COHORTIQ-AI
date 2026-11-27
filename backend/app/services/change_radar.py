"""Persisted, evidence-linked regulation comparisons and review status."""

from __future__ import annotations

import difflib
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.database import get_connection
from backend.app.audit.repository import append_audit_event
from backend.app.services import regulation_service

REVIEW_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS regulation_change_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    previous_regulation_id INTEGER NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
    new_regulation_id INTEGER NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('needs_review', 'approved')),
    applicable_batches TEXT NOT NULL CHECK (json_valid(applicable_batches) AND json_type(applicable_batches) = 'array'),
    applicable_programmes TEXT NOT NULL CHECK (json_valid(applicable_programmes) AND json_type(applicable_programmes) = 'array'),
    changes_json TEXT NOT NULL CHECK (json_valid(changes_json) AND json_type(changes_json) = 'array'),
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    reviewed_by INTEGER,
    reviewed_at TEXT
);
"""

_CLAUSE_START = re.compile(r"^\s*((?:\d+(?:\.\d+){0,6}[.)]?|[A-Z]\.\d+(?:\.\d+)*|[a-z]\)))\s+")
_MAX_CHANGES = 2000
_MAX_EXCERPT = 5000


def init_change_radar_tables(db_path: str | Path | None = None) -> None:
    with closing(get_connection(db_path)) as connection:
        connection.execute(REVIEW_TABLE_SQL)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_change_reviews_status ON regulation_change_reviews(status, id DESC);"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_change_reviews_new_regulation ON regulation_change_reviews(new_regulation_id);"
        )
        connection.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _clauses(pages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    for page in pages:
        page_number = page.get("page_number")
        text = page.get("extracted_text")
        if not isinstance(text, str) or not text.strip():
            continue
        current: list[str] = []
        current_label: str | None = None
        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                continue
            match = _CLAUSE_START.match(line)
            if match:
                if current:
                    value = " ".join(current).strip()
                    clauses.append({"page": page_number, "label": current_label, "text": value, "key": _normalize(value)})
                current = [line]
                current_label = match.group(1).rstrip(".)")
            elif current:
                current.append(line)
            else:
                current = [line]
                current_label = None
        if current:
            value = " ".join(current).strip()
            clauses.append({"page": page_number, "label": current_label, "text": value, "key": _normalize(value)})
    return [clause for clause in clauses if clause["key"]]


def _change(
    index: int,
    kind: str,
    old: Mapping[str, Any] | None,
    new: Mapping[str, Any] | None,
) -> dict[str, Any]:
    old_text = old["text"] if old else None
    new_text = new["text"] if new else None
    label = (new or old or {}).get("label")
    return {
        "id": index,
        "change_type": kind,
        "clause": str(label) if label else "Unnumbered passage",
        "previous_page": old.get("page") if old else None,
        "new_page": new.get("page") if new else None,
        "previous_text": old_text[:_MAX_EXCERPT] if old_text else None,
        "new_text": new_text[:_MAX_EXCERPT] if new_text else None,
        "previous_text_truncated": bool(old_text and len(old_text) > _MAX_EXCERPT),
        "new_text_truncated": bool(new_text and len(new_text) > _MAX_EXCERPT),
    }


def compare_pages(previous_pages: Sequence[Mapping[str, Any]], new_pages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Compare extracted passages deterministically; every result remains a potential change."""
    previous = _clauses(previous_pages)
    current = _clauses(new_pages)
    matcher = difflib.SequenceMatcher(
        a=[clause["key"] for clause in previous],
        b=[clause["key"] for clause in current],
        autojunk=False,
    )
    changes: list[dict[str, Any]] = []
    for opcode, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if opcode == "equal":
            continue
        old_items = previous[old_start:old_end]
        new_items = current[new_start:new_end]
        if opcode == "replace":
            paired = min(len(old_items), len(new_items))
            for offset in range(paired):
                changes.append(_change(len(changes) + 1, "modification", old_items[offset], new_items[offset]))
            old_items = old_items[paired:]
            new_items = new_items[paired:]
        for item in old_items:
            changes.append(_change(len(changes) + 1, "removal", item, None))
        for item in new_items:
            changes.append(_change(len(changes) + 1, "addition", None, item))
        if len(changes) > _MAX_CHANGES:
            raise ValueError("The comparison produced too many potential changes; compare smaller document sections.")
    return changes


def _decode_list(value: str) -> list[str]:
    decoded = json.loads(value)
    return [str(item) for item in decoded]


def _review_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "previous_regulation_id": int(row["previous_regulation_id"]),
        "previous_document_name": row["previous_document_name"],
        "previous_version": row["previous_version"],
        "new_regulation_id": int(row["new_regulation_id"]),
        "new_document_name": row["new_document_name"],
        "new_version": row["new_version"],
        "status": row["status"],
        "applicable_batches": _decode_list(row["applicable_batches"]),
        "applicable_programmes": _decode_list(row["applicable_programmes"]),
        "changes": json.loads(row["changes_json"]),
        "created_by": int(row["created_by"]),
        "created_at": row["created_at"],
        "reviewed_by": int(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
        "reviewed_at": row["reviewed_at"],
        "warning": (
            "Potential changes — review required."
            if row["status"] == "needs_review"
            else "Potential changes — administrator reviewed; verify the source documents."
        ),
    }


_SELECT_REVIEW = """
SELECT cr.*,
       old.document_name AS previous_document_name,
       old.regulation_version AS previous_version,
       new.document_name AS new_document_name,
       new.regulation_version AS new_version,
       new.verification_status AS new_verification_status
FROM regulation_change_reviews cr
JOIN regulations old ON old.id = cr.previous_regulation_id
JOIN regulations new ON new.id = cr.new_regulation_id
"""


def _load_pages(connection: sqlite3.Connection, regulation_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT page_number, extracted_text FROM document_pages WHERE regulation_id = ? ORDER BY page_number, id;",
        (regulation_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def create_review(
    *,
    previous_regulation_id: int,
    new_regulation_id: int,
    applicable_batches: list[str],
    applicable_programmes: list[str],
    administrator_id: int,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    init_change_radar_tables(db_path)
    with closing(get_connection(db_path)) as connection:
        connection.isolation_level = None
        connection.execute("BEGIN IMMEDIATE;")
        try:
            previous = connection.execute("SELECT * FROM regulations WHERE id = ?;", (previous_regulation_id,)).fetchone()
            new = connection.execute("SELECT * FROM regulations WHERE id = ?;", (new_regulation_id,)).fetchone()
            if previous is None or new is None:
                raise LookupError("A selected regulation version was not found.")
            if not regulation_service.is_approved(dict(previous)):
                raise ValueError("The previous regulation version must be approved.")
            if previous["document_name"].strip().casefold() != new["document_name"].strip().casefold():
                raise ValueError("Compare versions of the same regulation document.")
            if previous["regulation_version"] == new["regulation_version"]:
                raise ValueError("Choose regulation records with different version labels.")
            new_batches = set(_decode_list(new["applicable_batches"]))
            new_programmes = set(_decode_list(new["applicable_programmes"]))
            if (
                not applicable_batches
                or not applicable_programmes
                or not set(applicable_batches).issubset(new_batches)
                or not set(applicable_programmes).issubset(new_programmes)
            ):
                raise ValueError("Applicability must be selected from the new regulation's recorded batches and programmes.")
            changes = compare_pages(_load_pages(connection, previous_regulation_id), _load_pages(connection, new_regulation_id))
            if not changes:
                raise ValueError("No textual differences were detected; no review was created.")
            now = _now()
            cursor = connection.execute(
                """INSERT INTO regulation_change_reviews
                   (previous_regulation_id, new_regulation_id, status, applicable_batches,
                    applicable_programmes, changes_json, created_by, created_at)
                   VALUES (?, ?, 'needs_review', ?, ?, ?, ?, ?);""",
                (
                    previous_regulation_id,
                    new_regulation_id,
                    json.dumps(applicable_batches, ensure_ascii=False),
                    json.dumps(applicable_programmes, ensure_ascii=False),
                    json.dumps(changes, ensure_ascii=False),
                    administrator_id,
                    now,
                ),
            )
            review_id = int(cursor.lastrowid)
            append_audit_event(
                "regulation.change_reviewed",
                outcome="success",
                actor_type="user",
                actor_user_id=administrator_id,
                actor_role="administrator",
                target_type="regulation",
                target_id=new_regulation_id,
                details={"old_status": None, "new_status": "needs_review"},
                connection=connection,
            )
            connection.execute("COMMIT;")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK;")
            raise
    return get_review(review_id, db_path)


def get_review(review_id: int, db_path: str | Path | None = None) -> dict[str, Any] | None:
    init_change_radar_tables(db_path)
    with closing(get_connection(db_path)) as connection:
        row = connection.execute(_SELECT_REVIEW + " WHERE cr.id = ?;", (review_id,)).fetchone()
    return _review_from_row(row) if row else None


def list_reviews(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    init_change_radar_tables(db_path)
    with closing(get_connection(db_path)) as connection:
        rows = connection.execute(_SELECT_REVIEW + " ORDER BY cr.id DESC LIMIT 500;").fetchall()
    return [_review_from_row(row) for row in rows]


def list_published_updates(batch: str, programme: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    init_change_radar_tables(db_path)
    with closing(get_connection(db_path)) as connection:
        rows = connection.execute(
            _SELECT_REVIEW + " WHERE cr.status = 'approved' AND lower(trim(new.verification_status)) IN "
            "('approved','verified','administrator_verified','administrator_approved','verified_and_approved') "
            "ORDER BY cr.reviewed_at DESC, cr.id DESC LIMIT 500;"
        ).fetchall()
    updates = []
    for row in rows:
        review = _review_from_row(row)
        if batch in review["applicable_batches"] and programme in review["applicable_programmes"]:
            updates.append(review)
    return updates


def update_review_status(
    review_id: int,
    *,
    status: str,
    administrator_id: int,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    if status not in ("needs_review", "approved"):
        raise ValueError("Status must be 'needs_review' or 'approved'.")
    init_change_radar_tables(db_path)
    with closing(get_connection(db_path)) as connection:
        connection.isolation_level = None
        connection.execute("BEGIN IMMEDIATE;")
        try:
            current = connection.execute(
                "SELECT new_regulation_id, status FROM regulation_change_reviews WHERE id = ?;",
                (review_id,),
            ).fetchone()
            if current is None:
                connection.execute("COMMIT;")
                return None
            if current["status"] != status:
                now = _now()
                connection.execute(
                    "UPDATE regulation_change_reviews SET status = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?;",
                    (status, administrator_id, now, review_id),
                )
                append_audit_event(
                    "regulation.change_reviewed",
                    outcome="success",
                    actor_type="user",
                    actor_user_id=administrator_id,
                    actor_role="administrator",
                    target_type="regulation",
                    target_id=int(current["new_regulation_id"]),
                    details={"old_status": current["status"], "new_status": status},
                    connection=connection,
                )
            connection.execute("COMMIT;")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK;")
            raise
    return get_review(review_id, db_path)
