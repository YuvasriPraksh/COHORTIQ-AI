// Types mirroring the CohortIQ API schemas (backend/app/schemas/*.py, app/models.py).
// Only fields the API actually returns are declared.

/** POST /api/v1/auth/login response (TokenResponse). */
export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
}

/** GET /api/v1/auth/me response (UserProfileResponse). */
export interface UserProfile {
  id: number;
  email: string;
  role: "student" | "administrator";
  full_name: string | null;
  admission_batch: string | null;
  programme: string | null;
  is_active: boolean;
  created_at: string;
}

/** POST /api/v1/query/ask request body (StudentQuestionRequest; other fields use server defaults). */
export interface AskRequest {
  question: string;
  admission_batch: string;
  programme: string;
}

export type AnswerStatus = "answered" | "insufficient_evidence" | "conflicting_evidence";

/** GroundedCitation (app/models.py). */
export interface Citation {
  document_name: string | null;
  regulation_version: string | null;
  page_number: number | null;
  chunk_id: string | null;
  relevant_supporting_text: string | null;
}

/** GroundedAnswer (app/models.py). */
export interface GroundedAnswer {
  answer: string;
  status: AnswerStatus;
  citations: Citation[];
  limitations: string | null;
}

/** RetrievalResultItem: source metadata only, never chunk text. */
export interface RetrievalResult {
  chunk_id: string | number | null;
  regulation_id: string | number | null;
  document_name: string | null;
  regulation_version: string | null;
  page_number: number | null;
  admission_batch: string | null;
  programme: string | null;
  retrieval_score: number | null;
}

export interface RetrievalSummary {
  results: RetrievalResult[];
  status: string;
  message: string | null;
}

export type Route = "out_of_scope" | "clarify" | "clause_lookup" | "low_evidence" | "general";

/** RouteDecision (backend/app/schemas/routing.py). */
export interface RouteDecision {
  route: Route;
  reason: string;
  clause_number: string | null;
  top_k: number | null;
  best_score: number | null;
  min_score: number | null;
  threshold_applied: boolean;
}

/** POST /api/v1/query/ask response (GroundedAnswerResponse). */
export interface AskResponse {
  status: string;
  answer: GroundedAnswer;
  citations: Citation[];
  validation_issues: string[];
  retrieval: RetrievalSummary;
  route: RouteDecision | null;
}

/** Maximum question length accepted by the API (MAX_QUESTION_LENGTH default). */
export const MAX_QUESTION_LENGTH = 2000;
