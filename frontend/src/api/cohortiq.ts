import { ASK_TIMEOUT_MS, UPLOAD_TIMEOUT_MS, apiRequest } from "./client";
import type {
  AdminUser,
  AdminUserList,
  AskRequest,
  AskResponse,
  AccountRole,
  AuditEventList,
  Cohort,
  ChangeReview,
  DocumentPage,
  ImpactTwin,
  IngestionResult,
  RegisterRequest,
  Regulation,
  TokenResponse,
  UserProfile,
  VerificationStatus,
} from "./types";

const API = "/api/v1";

export function login(
  email: string,
  password: string,
  selectedRole?: AccountRole,
  signal?: AbortSignal,
): Promise<TokenResponse> {
  return apiRequest<TokenResponse>(`${API}/auth/login`, {
    method: "POST",
    body: { email, password, ...(selectedRole ? { selected_role: selectedRole } : {}) },
    signal,
  });
}

export function register(request: RegisterRequest, signal?: AbortSignal): Promise<UserProfile> {
  return apiRequest<UserProfile>(`${API}/auth/register`, { method: "POST", body: request, signal });
}

export function fetchProfile(token: string, signal?: AbortSignal): Promise<UserProfile> {
  return apiRequest<UserProfile>(`${API}/auth/me`, { token, signal });
}

export function askQuestion(token: string, request: AskRequest, signal?: AbortSignal): Promise<AskResponse> {
  return apiRequest<AskResponse>(`${API}/query/ask`, {
    method: "POST",
    body: request,
    token,
    signal,
    timeoutMs: ASK_TIMEOUT_MS,
  });
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function fetchHealth(signal?: AbortSignal): Promise<{ status: string }> {
  return apiRequest(`${API}/health`, { signal });
}

export async function fetchCohorts(signal?: AbortSignal): Promise<Cohort[]> {
  return (await apiRequest<{ cohorts: Cohort[] }>(`${API}/cohorts`, { signal })).cohorts;
}

/** Administrators receive every regulation; students and staff only approved ones. */
export async function listRegulations(token: string, signal?: AbortSignal): Promise<Regulation[]> {
  return (await apiRequest<{ regulations: Regulation[] }>(`${API}/regulations`, { token, signal })).regulations;
}

export async function listCohortRegulations(token: string, cohort: Cohort, signal?: AbortSignal): Promise<Regulation[]> {
  const batch = encodeURIComponent(cohort.admission_batch);
  const programme = encodeURIComponent(cohort.programme);
  const path = `${API}/cohorts/${batch}/${programme}/regulations`;
  return (await apiRequest<{ regulations: Regulation[] }>(path, { token, signal })).regulations;
}

export async function getRegulation(token: string, id: number, signal?: AbortSignal): Promise<Regulation> {
  return (await apiRequest<{ regulation: Regulation }>(`${API}/regulations/${id}`, { token, signal })).regulation;
}

export async function getRegulationPages(token: string, id: number, signal?: AbortSignal): Promise<DocumentPage[]> {
  return (await apiRequest<{ pages: DocumentPage[] }>(`${API}/regulations/${id}/pages`, { token, signal })).pages;
}

export function ingestRegulation(token: string, form: FormData): Promise<IngestionResult> {
  return apiRequest<IngestionResult>(`${API}/regulations/ingest`, {
    method: "POST",
    body: form,
    token,
    timeoutMs: UPLOAD_TIMEOUT_MS,
  });
}

export function setVerification(token: string, id: number, status: VerificationStatus): Promise<unknown> {
  return apiRequest(`${API}/regulations/${id}/verification`, {
    method: "PATCH",
    body: { verification_status: status },
    token,
  });
}

export function listUsers(
  token: string,
  params: { role?: string; is_active?: string; limit?: number; offset?: number } = {},
  signal?: AbortSignal,
): Promise<AdminUserList> {
  return apiRequest<AdminUserList>(`${API}/admin/users${query(params)}`, { token, signal });
}

export function createStudent(token: string, request: RegisterRequest): Promise<AdminUser> {
  return apiRequest<AdminUser>(`${API}/admin/users`, { method: "POST", body: request, token });
}

export function createStaff(token: string, request: RegisterRequest): Promise<AdminUser> {
  return apiRequest<AdminUser>(`${API}/admin/users/staff`, { method: "POST", body: request, token });
}

export function updateUser(
  token: string,
  id: number,
  changes: { full_name?: string | null; admission_batch?: string; programme?: string },
): Promise<AdminUser> {
  return apiRequest<AdminUser>(`${API}/admin/users/${id}`, { method: "PATCH", body: changes, token });
}

export type UserAction = "deactivate" | "reactivate" | "unlock" | "revoke-sessions";

export function runUserAction(token: string, id: number, action: UserAction): Promise<AdminUser> {
  return apiRequest<AdminUser>(`${API}/admin/users/${id}/${action}`, { method: "POST", token });
}

export function resetUserPassword(token: string, id: number, newPassword: string): Promise<AdminUser> {
  return apiRequest<AdminUser>(`${API}/admin/users/${id}/password`, {
    method: "POST",
    body: { new_password: newPassword },
    token,
  });
}

export function demoteToStudent(token: string, id: number): Promise<AdminUser> {
  return apiRequest<AdminUser>(`${API}/admin/users/${id}/role`, { method: "PATCH", body: { role: "student" }, token });
}

export function listAuditEvents(
  token: string,
  params: {
    action?: string;
    outcome?: string;
    actor_user_id?: number;
    target_type?: string;
    /** ISO 8601 with a timezone offset (the API requires one). */
    occurred_after?: string;
    occurred_before?: string;
    limit?: number;
    offset?: number;
  } = {},
  signal?: AbortSignal,
): Promise<AuditEventList> {
  return apiRequest<AuditEventList>(`${API}/admin/audit-events${query(params)}`, { token, signal });
}

export async function listChangeReviews(token: string, signal?: AbortSignal): Promise<ChangeReview[]> {
  return (await apiRequest<{ reviews: ChangeReview[] }>(`${API}/change-radar/reviews`, { token, signal })).reviews;
}

export function createChangeReview(
  token: string,
  request: {
    previous_regulation_id: number;
    new_regulation_id: number;
    applicable_batches: string[];
    applicable_programmes: string[];
  },
): Promise<ChangeReview> {
  return apiRequest<ChangeReview>(`${API}/change-radar/reviews`, { method: "POST", body: request, token });
}

export function setChangeReviewStatus(
  token: string,
  id: number,
  status: ChangeReview["status"],
): Promise<ChangeReview> {
  return apiRequest<ChangeReview>(`${API}/change-radar/reviews/${id}`, {
    method: "PATCH",
    body: { status },
    token,
  });
}

export async function listApprovedUpdates(token: string, signal?: AbortSignal): Promise<ChangeReview[]> {
  return (await apiRequest<{ updates: ChangeReview[] }>(`${API}/updates`, { token, signal })).updates;
}

/** Cohort-scoped impact of approved regulation changes; the cohort comes from the signed-in account. */
export function fetchImpactTwin(token: string, signal?: AbortSignal): Promise<ImpactTwin> {
  return apiRequest<ImpactTwin>(`${API}/impact-twin`, { token, signal });
}
