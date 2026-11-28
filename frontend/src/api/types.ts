// Types mirroring the CohortIQ API schemas (backend/app/schemas/*.py, app/models.py).
// Only fields the API actually returns are declared.

/** POST /api/v1/auth/login response (TokenResponse). */
export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
}

export type AccountRole = "student" | "staff" | "administrator";

/** GET /api/v1/auth/me response (UserProfileResponse). */
export interface UserProfile {
  id: number;
  email: string;
  role: AccountRole;
  full_name: string | null;
  admission_batch: string | null;
  programme: string | null;
  is_active: boolean;
  created_at: string;
}

/** POST /api/v1/auth/register request body (RegisterRequest). Students only; no role field. */
export interface RegisterRequest {
  email: string;
  password: string;
  admission_batch: string;
  programme: string;
  full_name?: string;
}

/** Domains are enforced by the backend; these values only explain the entry forms. */
export const STUDENT_EMAIL_DOMAIN: string = (import.meta.env.VITE_STUDENT_EMAIL_DOMAIN ?? "student.smvec.ac.in")
  .trim()
  .toLowerCase()
  .replace(/^@/, "");
export const STAFF_EMAIL_DOMAIN: string = (import.meta.env.VITE_STAFF_EMAIL_DOMAIN ?? "staff.smvec.ac.in")
  .trim()
  .toLowerCase()
  .replace(/^@/, "");
export const ADMINISTRATOR_EMAIL_DOMAIN: string = (
  import.meta.env.VITE_ADMINISTRATOR_EMAIL_DOMAIN ?? "admin.smvec.ac.in"
)
  .trim()
  .toLowerCase()
  .replace(/^@/, "");

export type ChunkingStrategy = "fixed_size" | "recursive" | "semantic";

/** POST /api/v1/query/ask request body (StudentQuestionRequest; other fields use server defaults). */
export interface AskRequest {
  question: string;
  admission_batch: string;
  programme: string;
  chunking_strategy?: ChunkingStrategy;
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

/** GET /api/v1/cohorts (CohortListResponse): cohorts covered by approved regulations. */
export interface Cohort {
  admission_batch: string;
  programme: string;
}

export type VerificationStatus = "approved" | "pending" | "rejected";

/** RegulationRecord (backend/app/schemas/regulations.py). */
export interface Regulation {
  id: number;
  document_name: string;
  regulation_version: string;
  effective_date: string | null;
  applicable_batches: string[];
  applicable_programmes: string[];
  upload_date: string | null;
  total_pages: number | null;
  processing_status: string | null;
  verification_status: string | null;
  source_filename?: string | null;
}

export interface DocumentPage {
  page_number: number;
  extracted_text: string | null;
  extraction_status: string | null;
}

export interface IngestionResult {
  status: string;
  regulation_id: number | null;
  verification_status: string | null;
  extraction_summary: {
    filename: string | null;
    total_pages: number | null;
    successful_pages: number | null;
    pages_needing_attention: number | null;
  } | null;
  message: string;
}

/** AdminUserResponse (backend/app/schemas/admin.py). */
export interface AdminUser {
  id: number;
  email: string;
  role: AccountRole;
  full_name: string | null;
  admission_batch: string | null;
  programme: string | null;
  is_active: boolean;
  is_locked: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminUserList {
  users: AdminUser[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditEvent {
  id: number;
  occurred_at: string;
  action: string;
  outcome: "success" | "failure" | "denied";
  actor_type: "user" | "anonymous" | "cli" | "system";
  actor_user_id: number | null;
  actor_role: AccountRole | null;
  target_type: "user" | "regulation" | null;
  target_id: number | null;
  details: Record<string, unknown>;
}

export interface AuditEventList {
  events: AuditEvent[];
  total: number;
  limit: number;
  offset: number;
}

export interface PotentialChange {
  id: number;
  change_type: "addition" | "removal" | "modification";
  clause: string;
  previous_page: number | null;
  new_page: number | null;
  previous_text: string | null;
  new_text: string | null;
  previous_text_truncated: boolean;
  new_text_truncated: boolean;
}

export interface ChangeReview {
  id: number;
  previous_regulation_id: number;
  previous_document_name: string;
  previous_version: string;
  new_regulation_id: number;
  new_document_name: string;
  new_version: string;
  status: "needs_review" | "approved";
  applicable_batches: string[];
  applicable_programmes: string[];
  changes: PotentialChange[];
  created_by: number;
  created_at: string;
  reviewed_by: number | null;
  reviewed_at: string | null;
  warning: string;
}

/** Upload limit enforced by the API (MAX_UPLOAD_BYTES default). */
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

/** GET /api/v1/impact-twin (backend/app/schemas/impact_twin.py). */
export type ImpactClassification = "potential_impact" | "no_direct_impact" | "requires_review";

export interface ImpactAssessment {
  review_id: number;
  change_id: number;
  document_name: string;
  previous_regulation_id: number;
  previous_version: string;
  new_regulation_id: number;
  new_version: string;
  reviewed_at: string | null;
  change_type: "addition" | "removal" | "modification";
  clause: string;
  previous_page: number | null;
  new_page: number | null;
  previous_text: string | null;
  new_text: string | null;
  previous_text_truncated: boolean;
  new_text_truncated: boolean;
  applicability: string;
  classification: ImpactClassification;
  classification_label: string;
  classification_reason: string;
  previous_values: string[];
  revised_values: string[];
  text_similarity: number;
  topics: string[];
  implications: string[];
  review_points: string[];
}

export interface ImpactTwin {
  cohort: { admission_batch: string; programme: string } | null;
  applicable_regulations: { id: number; document_name: string; regulation_version: string; effective_date: string | null }[];
  latest_update: {
    review_id: number;
    document_name: string;
    previous_version: string;
    new_version: string;
    reviewed_at: string | null;
    change_count: number;
  } | null;
  summary: { potential_impact: number; requires_review: number; no_direct_impact: number; total: number };
  assessments: ImpactAssessment[];
  personal_records_available: boolean;
  personalization_note: string;
}
