import { apiRequest } from "./client";
import type { AskRequest, AskResponse, TokenResponse, UserProfile } from "./types";

const API = "/api/v1";

export function login(email: string, password: string, signal?: AbortSignal): Promise<TokenResponse> {
  return apiRequest<TokenResponse>(`${API}/auth/login`, { method: "POST", body: { email, password }, signal });
}

export function fetchProfile(token: string, signal?: AbortSignal): Promise<UserProfile> {
  return apiRequest<UserProfile>(`${API}/auth/me`, { token, signal });
}

export function askQuestion(token: string, request: AskRequest, signal?: AbortSignal): Promise<AskResponse> {
  return apiRequest<AskResponse>(`${API}/query/ask`, { method: "POST", body: request, token, signal });
}
