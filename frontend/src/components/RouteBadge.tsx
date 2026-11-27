import type { AnswerStatus, RouteDecision } from "../api/types";

interface RouteCopy {
  label: string;
  tone: "good" | "neutral" | "caution";
  explain: (route: RouteDecision) => string;
}

const LOW_EVIDENCE_REASONS: Record<string, string> = {
  no_applicable_regulations: "No approved regulation applies to this admission batch and programme yet.",
  clause_not_found: "That clause number doesn't appear in the regulations for this cohort.",
  score_below_threshold: "The closest regulation text was too weak a match to support an answer.",
  no_retrieval_results: "No regulation text matched the question.",
};

function describeRoute(
  route: RouteDecision,
  answerStatus: AnswerStatus | string,
  hasCitations: boolean,
): RouteCopy | null {
  const isGrounded = answerStatus === "answered" && hasCitations;

  switch (route.route) {
    case "general":
      return {
        label: "Searched your regulations",
        tone: isGrounded ? "good" : answerStatus === "insufficient_evidence" ? "caution" : "neutral",
        explain: (r) =>
          isGrounded
            ? `Matched against the approved regulations for your cohort (top ${r.top_k ?? "?"} passages).`
            : `Searched the approved regulations for your cohort (top ${r.top_k ?? "?"} passages).`,
      };
    case "clause_lookup":
      return {
        label: "Clause lookup",
        tone: isGrounded ? "good" : answerStatus === "insufficient_evidence" ? "caution" : "neutral",
        explain: (r) =>
          `Looked up clause ${r.clause_number ?? ""} across the three closest approved passages.`.trim(),
      };
    case "low_evidence":
      return {
        label: "Not enough evidence",
        tone: "caution",
        explain: (r) => LOW_EVIDENCE_REASONS[r.reason] ?? "The regulations did not provide enough evidence to answer.",
      };
    case "out_of_scope":
      return {
        label: "Outside the regulations",
        tone: "neutral",
        explain: () => "This doesn't look like a question about academic regulations, so nothing was searched.",
      };
    case "clarify":
      return {
        label: "Needs your cohort",
        tone: "neutral",
        explain: () => "Your admission batch and programme are needed to find the regulations that apply.",
      };
    default:
      return null;
  }
}

export function RouteBadge({
  route,
  answerStatus,
  hasCitations,
}: {
  route: RouteDecision;
  answerStatus: AnswerStatus | string;
  hasCitations: boolean;
}) {
  const copy = describeRoute(route, answerStatus, hasCitations);
  if (!copy) return null;
  return (
    <div className={`route route--${copy.tone}`}>
      <span className="route__label">
        <span className="route__dot" aria-hidden="true" />
        <span className="visually-hidden">How this question was handled: </span>
        {copy.label}
      </span>
      <span className="route__explain">{copy.explain(route)}</span>
    </div>
  );
}
