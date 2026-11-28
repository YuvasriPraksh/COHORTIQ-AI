"""My Academic Impact Twin: cohort-level impact assessment of approved regulation changes.

Responsibilities (distinct from Chat and Change Radar):
- Change Radar detects differences between two regulation versions and an
  administrator approves the review.
- This service takes only *published* reviews (review approved by an
  administrator AND the new regulation approved AND the authenticated cohort in
  the review's recorded applicability) and classifies each detected change by
  comparing the previous and revised clause text.

Boundaries:
- Classifications are derived deterministically from the clause texts; nothing
  is generated or inferred beyond what the two passages contain.
- No individual academic records exist in CohortIQ, so no statement here says a
  student is eligible or ineligible. ``PersonalRecordProvider`` marks the seam
  where verified records (attendance, credits, marks) could be plugged in later
  for individual simulations.
"""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol

from app.database import get_applicable_regulations
from backend.app.services import change_radar

POTENTIAL_IMPACT = "potential_impact"
NO_DIRECT_IMPACT = "no_direct_impact"
REQUIRES_REVIEW = "requires_review"

CLASSIFICATION_LABELS = {
    POTENTIAL_IMPACT: "Potential Impact",
    NO_DIRECT_IMPACT: "No Direct Impact Identified",
    REQUIRES_REVIEW: "Requires Review",
}
_ORDER = {POTENTIAL_IMPACT: 0, REQUIRES_REVIEW: 1, NO_DIRECT_IMPACT: 2}

# Wording-only edits at or above this token similarity (with identical numbers)
# are treated as having no direct impact.
MINOR_WORDING_SIMILARITY = 0.92

_CLAUSE_PREFIX = re.compile(r"^\s*(?:\d+(?:\.\d+){0,6}[.)]?|[A-Z]\.\d+(?:\.\d+)*|[a-z]\))\s+")
_NUMBER = re.compile(r"(?<![\w.\-])(\d+(?:\.\d+)?)\s*(%|percent\b|per\s+cent\b)?", re.IGNORECASE)
_TOKEN = re.compile(r"[a-z0-9]+")

TOPICS: dict[str, tuple[str, ...]] = {
    "attendance": ("attendance",),
    "credits": ("credit",),
    "grading and CGPA": ("grade", "grading", "cgpa", "sgpa", "gpa"),
    "examinations and assessment": ("examination", "exam ", "assessment", "continuous assessment", "cat "),
    "arrears and re-registration": ("arrear", "re-registration", "reregistration", "supplementary", "reappear"),
    "semester progression": ("next semester", "higher semester", "promotion", "move to the next"),
    "degree award and eligibility": ("eligib", "award of degree", "honours", "minor degree", "classification"),
}


class PersonalRecordProvider(Protocol):
    """Future integration point for verified individual academic records (not implemented)."""

    def records_for(self, user_id: str) -> Optional[Mapping[str, Any]]: ...


def _body(text: Optional[str]) -> str:
    return _CLAUSE_PREFIX.sub("", text or "", count=1).strip()


_YEAR = re.compile(r"^(19|20)\d{2}$")
_CONTENTS = re.compile(r"\u2026{3,}|\.{5,}|\bpage\s+no\b|\bcontents\b", re.IGNORECASE)
_GRADE_CONTEXT = re.compile(r"cgpa|sgpa|gpa|grade point|marks?\b")

# Below this token similarity the two paired passages are treated as different
# provisions (a restructuring), so differing numbers are not read as a changed value.
UNRELATED_SIMILARITY = 0.35


def _numbers(text: Optional[str], ignore: frozenset[str] = frozenset()) -> list[str]:
    """Numeric values that can express a requirement (percentages, marks, credits, counts).

    Edition years (1900-2099 without a % sign) and the cited page numbers are
    ignored: they come from running headers and footers, not from rules.
    """
    body = _body(text)
    if _CONTENTS.search(body):
        return []  # a table of contents lists page numbers, not requirements
    values = []
    for match in _NUMBER.finditer(body):
        number, unit = match.group(1), match.group(2)
        if unit:
            values.append(f"{number}%")
            continue
        if _YEAR.match(number) or number in ignore:
            continue
        if "." in number:
            # Dotted numbers are clause references ("vide Regulation 7.11") unless they
            # sit next to a grade term ("CGPA of not less than 8.0").
            context = body[max(0, match.start() - 40): match.start()].lower()
            if not _GRADE_CONTEXT.search(context):
                continue
        values.append(number)
    return values


def _tokens(text: Optional[str]) -> list[str]:
    return _TOKEN.findall(_body(text).lower())


def _topics(*texts: Optional[str]) -> list[str]:
    haystack = " ".join(t or "" for t in texts).lower() + " "
    return [topic for topic, words in TOPICS.items() if any(word in haystack for word in words)]


def classify_change(change: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one Change Radar difference from its previous and revised text only."""
    kind = change.get("change_type")
    previous_text = change.get("previous_text")
    new_text = change.get("new_text")
    pages = frozenset(str(p) for p in (change.get("previous_page"), change.get("new_page")) if p is not None)
    previous_numbers = _numbers(previous_text, pages)
    new_numbers = _numbers(new_text, pages)
    removed_values = sorted((Counter(previous_numbers) - Counter(new_numbers)).elements())
    added_values = sorted((Counter(new_numbers) - Counter(previous_numbers)).elements())
    similarity = SequenceMatcher(None, _tokens(previous_text), _tokens(new_text)).ratio() if previous_text and new_text else 0.0

    if kind == "addition":
        classification = REQUIRES_REVIEW
        reason = "A clause appears in the revised version that has no matching passage in the previous version."
    elif kind == "removal":
        classification = REQUIRES_REVIEW
        reason = "A clause from the previous version has no matching passage in the revised version."
    elif similarity < UNRELATED_SIMILARITY:
        classification = REQUIRES_REVIEW
        reason = (
            "The paired passages are substantially different, so this may be a restructured or relocated provision "
            "rather than a changed value; read both passages."
        )
    elif removed_values or added_values:
        classification = POTENTIAL_IMPACT
        reason = "Numeric values in this clause changed between the two versions."
    elif similarity >= MINOR_WORDING_SIMILARITY:
        classification = NO_DIRECT_IMPACT
        reason = "Only minor wording differences were detected; all numeric values are unchanged."
    else:
        classification = REQUIRES_REVIEW
        reason = "The wording changed substantially while numeric values stayed the same; read both passages."

    return {
        "classification": classification,
        "classification_label": CLASSIFICATION_LABELS[classification],
        "classification_reason": reason,
        "previous_values": removed_values,
        "revised_values": added_values,
        "text_similarity": round(similarity, 2),
        "topics": _topics(previous_text, new_text),
    }


def _implications(change: Mapping[str, Any], signals: Mapping[str, Any]) -> list[str]:
    topics = signals["topics"]
    topic_text = ", ".join(topics) if topics else "a general academic provision"
    items = [f"This clause relates to {topic_text}."]
    if signals["classification"] == POTENTIAL_IMPACT:
        before = ", ".join(signals["previous_values"]) or "none"
        after = ", ".join(signals["revised_values"]) or "none"
        items.append(
            f"Values that appear only in the previous text: {before}. Values that appear only in the revised text: {after}. "
            "If this clause governs a requirement you must meet, the requirement may now be different."
        )
    elif signals["classification"] == NO_DIRECT_IMPACT:
        items.append("No change to numbers or substantive wording was found, so no direct effect on requirements was identified.")
    elif change.get("change_type") == "addition":
        items.append("New text may introduce a requirement or option that did not exist before. Its effect depends on its full context.")
    elif change.get("change_type") == "removal":
        items.append("A provision that existed before may no longer apply. Check whether another clause replaces it.")
    else:
        items.append("The meaning of the clause may have changed even though no numbers changed.")
    return items


def _review_points(review: Mapping[str, Any], change: Mapping[str, Any], signals: Mapping[str, Any]) -> list[str]:
    points = []
    if change.get("new_page") is not None:
        points.append(f"Read the revised clause on page {change['new_page']} of {review['new_document_name']} {review['new_version']}.")
    if change.get("previous_page") is not None:
        points.append(f"Compare it with page {change['previous_page']} of the previous version {review['previous_version']}.")
    if signals["classification"] == POTENTIAL_IMPACT:
        points.append("Check how the changed values apply to your own situation.")
    if change.get("previous_text_truncated") or change.get("new_text_truncated"):
        points.append("The excerpt was shortened; read the full page for complete context.")
    points.append("CohortIQ does not hold your attendance, credits or marks. Confirm your personal position with your department or academic office.")
    return points


def build_assessment(
    *,
    user_id: str,
    admission_batch: Optional[str],
    programme: Optional[str],
    db_path: str | Path | None = None,
    records: Optional[PersonalRecordProvider] = None,
) -> dict[str, Any]:
    """Impact assessment for the authenticated account's stored cohort."""
    base: dict[str, Any] = {
        "cohort": None,
        "applicable_regulations": [],
        "latest_update": None,
        "summary": {POTENTIAL_IMPACT: 0, REQUIRES_REVIEW: 0, NO_DIRECT_IMPACT: 0, "total": 0},
        "assessments": [],
        "personal_records_available": False,
        "personalization_note": (
            "This is a cohort-level assessment based on regulation text. CohortIQ has no verified individual academic "
            "records (attendance, credits, marks), so it cannot say whether any change affects you personally."
        ),
    }
    if records is not None and records.records_for(user_id):  # pragma: no cover - future integration
        base["personal_records_available"] = True
    if not admission_batch or not programme:
        return base

    base["cohort"] = {"admission_batch": admission_batch, "programme": programme}
    base["applicable_regulations"] = [
        {
            "id": int(reg["id"]),
            "document_name": reg["document_name"],
            "regulation_version": reg["regulation_version"],
            "effective_date": reg.get("effective_date"),
        }
        for reg in get_applicable_regulations(admission_batch, programme, db_path=db_path)
    ]

    updates = change_radar.list_published_updates(admission_batch, programme, db_path)
    if updates:
        latest = updates[0]
        base["latest_update"] = {
            "review_id": latest["id"],
            "document_name": latest["new_document_name"],
            "previous_version": latest["previous_version"],
            "new_version": latest["new_version"],
            "reviewed_at": latest["reviewed_at"],
            "change_count": len(latest["changes"]),
        }

    assessments = []
    for review in updates:
        for change in review["changes"]:
            signals = classify_change(change)
            assessments.append(
                {
                    "review_id": review["id"],
                    "change_id": change["id"],
                    "document_name": review["new_document_name"],
                    "previous_regulation_id": review["previous_regulation_id"],
                    "previous_version": review["previous_version"],
                    "new_regulation_id": review["new_regulation_id"],
                    "new_version": review["new_version"],
                    "reviewed_at": review["reviewed_at"],
                    "change_type": change["change_type"],
                    "clause": change["clause"],
                    "previous_page": change.get("previous_page"),
                    "new_page": change.get("new_page"),
                    "previous_text": change.get("previous_text"),
                    "new_text": change.get("new_text"),
                    "previous_text_truncated": bool(change.get("previous_text_truncated")),
                    "new_text_truncated": bool(change.get("new_text_truncated")),
                    "applicability": (
                        f"An administrator recorded this update for Batch {admission_batch} · {programme}, "
                        "which matches the cohort on your account."
                    ),
                    **signals,
                    "implications": _implications(change, signals),
                    "review_points": _review_points(review, change, signals),
                }
            )
    assessments.sort(key=lambda item: (_ORDER[item["classification"]], item["review_id"] * -1, item["change_id"]))
    counts = Counter(item["classification"] for item in assessments)
    base["summary"] = {
        POTENTIAL_IMPACT: counts.get(POTENTIAL_IMPACT, 0),
        REQUIRES_REVIEW: counts.get(REQUIRES_REVIEW, 0),
        NO_DIRECT_IMPACT: counts.get(NO_DIRECT_IMPACT, 0),
        "total": len(assessments),
    }
    base["assessments"] = assessments
    return base
