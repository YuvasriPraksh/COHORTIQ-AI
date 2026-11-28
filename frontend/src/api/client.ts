// Minimal fetch wrapper for the CohortIQ API. Errors become ApiError with a
// message that is safe to show to students; details the API never returns are
// not invented.

/** API origin. Empty in development (the Vite proxy forwards /api). */
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export const DEFAULT_TIMEOUT_MS = 15_000;
// Grounded answers wait for Gemini; measured latencies reached ~52 s, so allow two minutes.
export const ASK_TIMEOUT_MS = 120_000;
export const UPLOAD_TIMEOUT_MS = 120_000;

export type ApiErrorKind =
  | "network"
  | "timeout"
  | "unauthorized"
  | "forbidden"
  | "invalid"
  | "too_large"
  | "unavailable"
  | "not_found"
  | "conflict"
  | "server";

export class ApiError extends Error {
  readonly status: number | null;
  readonly kind: ApiErrorKind;

  constructor(kind: ApiErrorKind, message: string, status: number | null) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }
}

interface ValidationIssue {
  msg?: unknown;
}

/** Turn a FastAPI error body into one readable sentence. */
function describeDetail(detail: unknown): string | null {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((issue: ValidationIssue) => (typeof issue?.msg === "string" ? issue.msg.replace(/^Value error, /, "") : null))
      .filter((message): message is string => Boolean(message));
    return messages.length ? messages.join(" ") : null;
  }
  return null;
}

function errorFor(status: number, detail: string | null): ApiError {
  if (status === 401) {
    return new ApiError("unauthorized", detail ?? "Your session has ended. Please sign in again.", status);
  }
  if (status === 403) {
    return new ApiError("forbidden", detail ?? "You do not have permission to do that.", status);
  }
  if (status === 400 || status === 422) {
    return new ApiError("invalid", detail ?? "Please check what you entered and try again.", status);
  }
  if (status === 404) {
    return new ApiError("not_found", detail ?? "That record could not be found.", status);
  }
  if (status === 409) {
    return new ApiError("conflict", detail ?? "That change conflicts with the current record.", status);
  }
  if (status === 413) {
    return new ApiError("too_large", detail ?? "That request is too large.", status);
  }
  if (status === 503) {
    return new ApiError("unavailable", detail ?? "The service is temporarily unavailable. Please try again shortly.", status);
  }
  return new ApiError("server", detail ?? "Something went wrong on our side. Please try again later.", status);
}

export async function apiRequest<T>(
  path: string,
  options: {
    method?: "GET" | "POST" | "PATCH";
    body?: unknown;
    token?: string | null;
    signal?: AbortSignal;
    timeoutMs?: number;
  } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  // FormData sets its own multipart Content-Type (with the boundary).
  const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (options.body !== undefined && !isForm) {
    headers["Content-Type"] = "application/json";
  }
  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }

  const controller = new AbortController();
  let timedOut = false;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const externalSignal = options.signal;
  const onExternalAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) {
      window.clearTimeout(timer);
      throw new DOMException("The operation was aborted.", "AbortError");
    }
    externalSignal.addEventListener("abort", onExternalAbort, { once: true });
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers,
      body:
        options.body === undefined ? undefined : isForm ? (options.body as FormData) : JSON.stringify(options.body),
      signal: controller.signal,
    });
  } catch (error) {
    if (externalSignal?.aborted) {
      throw new DOMException("The operation was aborted.", "AbortError");
    }
    if (timedOut) {
      throw new ApiError(
        "timeout",
        "The request took too long to finish. Please try again.",
        null,
      );
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError("network", "We couldn't reach the CohortIQ server. Check your connection and try again.", null);
  } finally {
    window.clearTimeout(timer);
    externalSignal?.removeEventListener("abort", onExternalAbort);
  }

  let payload: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const detail = describeDetail((payload as { detail?: unknown } | null)?.detail);
    // Server errors keep their generic API message; never surface raw bodies.
    throw errorFor(response.status, detail);
  }
  if (payload === null) {
    throw new ApiError("server", "The server sent an unexpected response.", response.status);
  }
  return payload as T;
}
