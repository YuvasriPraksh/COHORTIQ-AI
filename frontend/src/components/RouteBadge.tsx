import type { RouteDecision } from "../api/types";

interface RouteCopy {
  label: string;
  tone: "good" | "neutral" | "caution";
  explain: (route: RouteDecision) => string;
}

// Plain-language descriptions of the Adaptive RAG router's decisions
// (backend/app/services/adaptive_router.py).
const ROUTES: Record<RouteDecision["route"], RouteCopy> = {
  general: {
    label: "Searched your regulations",
    tone: "good",
    explain: (r) => `Matched against the approved regulations for your cohort (top ${r.top_k ?? "?"} passages).`,
  },
  clause_lookup: {
    label: "Clause lookup",
    tone: "good",
    explain: (r) => `You asked about clause ${r.clause_number ?? ""}, so the three closest passages were used.`,
  },
  low_evidence: {
    label: "Not enough evidence",
    tone: "caution",
    explain: (r) => LOW_EVIDENCE_REASONS[r.reason] ?? "The regulations did not provide enough evidence to answer.",
  },
  out_of_scope: {
    label: "Outside the regulations",
    tone: "neutral",
    explain: () => "This doesn't look like a question about academic regulations, so nothing was searched.",
  },
  clarify: {
    label: "Needs your cohort",
    tone: "neutral",
    explain: () => "Your admission batch and programme are needed to find the regulations that apply.",
  },
};

const LOW_EVIDENCE_REASONS: Record<string, string> = {
  no_applicable_regulations: "No approved regulation applies to this admission batch and programme yet.",
  clause_not_found: "That clause number doesn't appear in the regulations for this cohort.",
  score_below_threshold: "The closest regulation text was too weak a match to support an answer.",
  no_retrieval_results: "No regulation text matched the question.",
};

export function RouteBadge({ route }: { route: RouteDecision }) {
  const copy = ROUTES[route.route];
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
