import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AskResponse, ChangeReview, Regulation, UserProfile } from "./api/types";
import { SessionProvider } from "./auth/session";

// ---------------------------------------------------------------------------
// Fixtures shaped exactly like the API responses
// ---------------------------------------------------------------------------

const STUDENT: UserProfile = {
  id: 7,
  email: "asha@student.smvec.ac.in",
  role: "student",
  full_name: "Asha Kumar",
  admission_batch: "2024",
  programme: "B-tech - CSE",
  is_active: true,
  created_at: "2026-01-10T09:00:00Z",
};

const ADMIN: UserProfile = { ...STUDENT, id: 1, role: "administrator", full_name: null, email: "admin@admin.smvec.ac.in", admission_batch: null, programme: null };
const STAFF: UserProfile = { ...STUDENT, id: 2, role: "staff", full_name: "Taylor Teacher", email: "teacher@staff.smvec.ac.in" };

const ANSWERED: AskResponse = {
  status: "answered",
  answer: {
    answer: "You need at least 75% attendance to write the end semester examination.",
    status: "answered",
    citations: [],
    limitations: null,
  },
  citations: [
    {
      document_name: "SMVEC",
      regulation_version: "2023",
      page_number: 21,
      chunk_id: "1-21-0",
      relevant_supporting_text: "only if he/she maintains minimum 75% of attendance",
    },
  ],
  validation_issues: [],
  retrieval: {
    status: "ok",
    message: "Retrieved 2 relevant chunk(s).",
    results: [
      { chunk_id: "1-21-0", regulation_id: 1, document_name: "SMVEC", regulation_version: "2023", page_number: 21, admission_batch: "2024", programme: "B-tech - CSE", retrieval_score: 15.01 },
      { chunk_id: "1-14-0", regulation_id: 1, document_name: "SMVEC", regulation_version: "2023", page_number: 14, admission_batch: "2024", programme: "B-tech - CSE", retrieval_score: 14.05 },
    ],
  },
  route: { route: "general", reason: "evidence_found", clause_number: null, top_k: 5, best_score: 15.01, min_score: 3, threshold_applied: true },
};

function unanswered(route: AskResponse["route"], answer: string, limitations: string): AskResponse {
  return {
    status: "insufficient_evidence",
    answer: { answer, status: "insufficient_evidence", citations: [], limitations },
    citations: [],
    validation_issues: [],
    retrieval: { status: route?.route === "out_of_scope" || route?.route === "clarify" ? "skipped" : "no_evidence", message: limitations, results: [] },
    route,
  };
}

const OUT_OF_SCOPE = unanswered(
  { route: "out_of_scope", reason: "no_regulation_terms", clause_number: null, top_k: null, best_score: null, min_score: null, threshold_applied: false },
  "I can only answer questions about the academic regulations that apply to your cohort.",
  "The question does not appear to be about academic regulations, so no regulation was searched.",
);

const LOW_EVIDENCE = unanswered(
  { route: "low_evidence", reason: "score_below_threshold", clause_number: null, top_k: 5, best_score: 1.2, min_score: 3, threshold_applied: true },
  "I cannot provide a grounded answer because the approved regulations for your cohort do not appear to cover this question.",
  "The best matching regulation text was too weak to support an answer.",
);

// ---------------------------------------------------------------------------
// fetch mock
// ---------------------------------------------------------------------------

type Reply = { status: number; body?: unknown } | Error;
interface Call {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

function mockApi(routes: Record<string, Reply | Reply[]>) {
  const calls: Call[] = [];
  const queues = new Map(Object.entries(routes).map(([key, value]) => [key, Array.isArray(value) ? [...value] : [value]]));
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    calls.push({
      url,
      method,
      headers: (init.headers ?? {}) as Record<string, string>,
      body: init.body ? JSON.parse(String(init.body)) : undefined,
    });
    const queue = queues.get(`${method} ${url}`);
    if (!queue?.length) throw new Error(`Unexpected request ${method} ${url}`);
    const reply = queue.length > 1 ? queue.shift()! : queue[0]!;
    if (reply instanceof Error) throw reply;
    return new Response(reply.body === undefined ? "" : JSON.stringify(reply.body), {
      status: reply.status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

const LOGIN = "POST /api/v1/auth/login";
const ME = "GET /api/v1/auth/me";
const ASK = "POST /api/v1/query/ask";
const COHORTS = "GET /api/v1/cohorts";
const AVAILABLE_COHORTS = {
  status: 200,
  body: { cohorts: [{ admission_batch: "2024", programme: "B-tech - CSE" }] },
};
const TOKEN = { status: 200, body: { access_token: "token-abc", token_type: "bearer", expires_in: 1800 } };
const CHANGE_RADAR_REGULATIONS: Regulation[] = [
  {
    id: 21,
    document_name: "Academic Regulation",
    regulation_version: "2023",
    effective_date: "2023-01-01",
    applicable_batches: ["2024"],
    applicable_programmes: ["B-tech - CSE"],
    upload_date: "2023-01-01",
    total_pages: 1,
    processing_status: "extracted",
    verification_status: "approved",
  },
  {
    id: 22,
    document_name: "Academic Regulation",
    regulation_version: "2024",
    effective_date: "2024-01-01",
    applicable_batches: ["2024"],
    applicable_programmes: ["B-tech - CSE"],
    upload_date: "2024-01-01",
    total_pages: 1,
    processing_status: "extracted",
    verification_status: "pending",
  },
];
const CHANGE_REVIEW: ChangeReview = {
  id: 11,
  previous_regulation_id: 21,
  previous_document_name: "Academic Regulation",
  previous_version: "2023",
  new_regulation_id: 22,
  new_document_name: "Academic Regulation",
  new_version: "2024",
  status: "needs_review",
  applicable_batches: ["2024"],
  applicable_programmes: ["B-tech - CSE"],
  changes: [
    {
      id: 1,
      change_type: "modification",
      clause: "5.1",
      previous_page: 12,
      new_page: 14,
      previous_text: "Minimum attendance is 75%.",
      new_text: "Minimum attendance is 80%.",
      previous_text_truncated: false,
      new_text_truncated: false,
    },
  ],
  created_by: 1,
  created_at: "2026-01-10T09:00:00Z",
  reviewed_by: null,
  reviewed_at: null,
  warning: "Potential changes — review required.",
};

function renderApp() {
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  return render(
    <SessionProvider>
      <App />
    </SessionProvider>,
  );
}

async function signIn(user = userEvent.setup(), role: "student" | "staff" | "administrator" = "student") {
  renderApp();
  const title = role === "student" ? "Student" : role === "staff" ? "Staff / Teacher" : "Administrator";
  const card = (await screen.findByRole("heading", { name: title })).closest("article");
  if (!card) throw new Error(`Missing ${title} role card.`);
  await user.click(within(card).getByRole("button", { name: "Continue" }));
  await user.type(
    await screen.findByLabelText("Email"),
    role === "student" ? "asha@student.smvec.ac.in" : role === "staff" ? "teacher@staff.smvec.ac.in" : "admin@admin.smvec.ac.in",
  );
  await user.type(screen.getByLabelText("Password"), "Correct-horse-9");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  return user;
}

async function ask(user: ReturnType<typeof userEvent.setup>, text: string) {
  const box = await screen.findByLabelText("Your question");
  await user.clear(box);
  await user.type(box, text);
  await user.click(screen.getByRole("button", { name: "Ask" }));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("sign in → ask → answer", () => {
  it("signs in, asks with the stored cohort, and shows the answer, evidence and route", async () => {
    const calls = mockApi({ [LOGIN]: TOKEN, [ME]: { status: 200, body: STUDENT }, [ASK]: { status: 200, body: ANSWERED } });

    const user = await signIn();
    const cohortSummary = screen.getByLabelText("Cohort used for your question");
    expect(within(cohortSummary).getByText("Batch 2024")).toBeInTheDocument();
    expect(within(cohortSummary).getByText("B-tech - CSE")).toBeInTheDocument();
    await ask(user, "What attendance do I need?");

    expect(await screen.findByRole("heading", { name: "Answer" })).toHaveFocus();
    expect(screen.getByText(ANSWERED.answer.answer)).toBeInTheDocument();
    expect(screen.getByText("Searched your regulations")).toBeInTheDocument();
    const evidence = screen.getByRole("region", { name: /Evidence/ });
    expect(within(evidence).getByText("SMVEC")).toBeInTheDocument();
    expect(within(evidence).getByText("v2023")).toBeInTheDocument();
    expect(within(evidence).getByText("Page 21")).toBeInTheDocument();
    expect(within(evidence).getByText(ANSWERED.citations[0]!.relevant_supporting_text!)).toBeInTheDocument();
    expect(screen.getByText("Passages searched")).toBeInTheDocument();
    expect(screen.getAllByText("Grounded answer").length).toBeGreaterThan(0);
    expect(screen.queryByText(/match 15\.0/i)).not.toBeInTheDocument();

    expect(calls[0]).toMatchObject({
      url: "/api/v1/auth/login",
      body: { email: "asha@student.smvec.ac.in", password: "Correct-horse-9", selected_role: "student" },
    });
    const askCall = calls.find((call) => call.url === "/api/v1/query/ask")!;
    expect(askCall.headers.Authorization).toBe("Bearer token-abc");
    expect(askCall.body).toEqual({ question: "What attendance do I need?", admission_batch: "2024", programme: "B-tech - CSE" });
  });

  it("shows the API's generic message when sign-in fails", async () => {
    mockApi({ [LOGIN]: { status: 401, body: { detail: "Incorrect email or password." } } });

    await signIn();

    expect(await screen.findByText("Incorrect email or password.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("asks for both fields before calling the API", async () => {
    const calls = mockApi({});
    const user = userEvent.setup();
    renderApp();

    const studentCard = (await screen.findByRole("heading", { name: "Student" })).closest("article");
    if (!studentCard) throw new Error("Missing student role card.");
    await user.click(within(studentCard).getByRole("button", { name: "Continue" }));
    await user.click(await screen.findByRole("button", { name: "Sign in" }));

    expect(screen.getByText("Enter your email and password.")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });
});

describe("answer states", () => {
  it("explains an out-of-scope refusal without showing evidence", async () => {
    mockApi({ [LOGIN]: TOKEN, [ME]: { status: 200, body: STUDENT }, [ASK]: { status: 200, body: OUT_OF_SCOPE } });

    await ask(await signIn(), "Who won the cricket world cup in 2011?");

    expect(await screen.findByRole("heading", { name: "Outside what I can answer" })).toBeInTheDocument();
    expect(screen.getByText("Outside the regulations")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Evidence/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Passages searched")).not.toBeInTheDocument();
  });

  it("shows an abstention as 'no grounded answer' with the reason", async () => {
    mockApi({ [LOGIN]: TOKEN, [ME]: { status: 200, body: STUDENT }, [ASK]: { status: 200, body: LOW_EVIDENCE } });

    await ask(await signIn(), "Can the honours syllabus change?");

    expect(await screen.findByRole("heading", { name: "No grounded answer" })).toBeInTheDocument();
    expect(screen.getByText("Not enough evidence")).toBeInTheDocument();
    expect(screen.getByText(/too weak a match to support an answer/)).toBeInTheDocument();
    expect(screen.getByText(LOW_EVIDENCE.answer.limitations!)).toBeInTheDocument();
  });

  it("shows a clarification request when the router asks for the cohort", async () => {
    const clarify = unanswered(
      { route: "clarify", reason: "missing_cohort", clause_number: null, top_k: null, best_score: null, min_score: null, threshold_applied: false },
      "Please tell me your admission batch and programme so I can find the regulations that apply to you.",
      "Cohort details are missing, so the applicable regulations cannot be determined.",
    );
    mockApi({ [LOGIN]: TOKEN, [ME]: { status: 200, body: STUDENT }, [ASK]: { status: 200, body: clarify } });

    await ask(await signIn(), "What attendance is needed?");

    expect(await screen.findByRole("heading", { name: "I need your cohort first" })).toBeInTheDocument();
    expect(screen.getByText("Needs your cohort")).toBeInTheDocument();
  });

  it("lists citations the backend removed during validation", async () => {
    const withIssues = { ...ANSWERED, validation_issues: ["Citation 2 did not match the retrieved evidence."] };
    mockApi({ [LOGIN]: TOKEN, [ME]: { status: 200, body: STUDENT }, [ASK]: { status: 200, body: withIssues } });

    await ask(await signIn(), "What attendance do I need?");

    expect(await screen.findByText("Some citations were removed")).toBeInTheDocument();
    expect(screen.getByText("Citation 2 did not match the retrieved evidence.")).toBeInTheDocument();
  });

  it("sanitizes raw chunk IDs, deduplicates validation notices, and adjusts route tone when downgraded", async () => {
    const downgraded: AskResponse = {
      status: "insufficient_evidence",
      answer: {
        answer: "The available retrieved evidence is insufficient to provide a fully grounded answer with valid supporting citations.",
        status: "insufficient_evidence",
        citations: [],
        limitations:
          "Citation validation failed: no valid supporting citations matched the original retrieved evidence. Rejected citation for chunk_id '1-p21-c61' because supporting text could not be matched to evidence.",
      },
      citations: [],
      validation_issues: [
        "Rejected citation for chunk_id '1-p21-c61' because supporting text could not be matched to evidence.",
      ],
      retrieval: ANSWERED.retrieval,
      route: ANSWERED.route,
    };
    mockApi({ [LOGIN]: TOKEN, [ME]: { status: 200, body: STUDENT }, [ASK]: { status: 200, body: downgraded } });

    await ask(await signIn(), "What attendance do I need?");

    expect(await screen.findByRole("heading", { name: "No grounded answer" })).toBeInTheDocument();
    expect(screen.getByText("References could not be verified")).toBeInTheDocument();
    expect(
      screen.getByText("A draft reference could not be matched to the regulation text and was removed."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/chunk_id/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/1-p21-c61/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Note:$/)).not.toBeInTheDocument();
    const routeEl = screen.getByText("Searched your regulations").closest(".route");
    expect(routeEl).not.toHaveClass("route--good");
  });

  it("never shows a grounded verdict badge when answered has zero citations", async () => {
    const noCitations: AskResponse = {
      ...ANSWERED,
      citations: [],
      answer: { ...ANSWERED.answer, citations: [] },
    };
    mockApi({ [LOGIN]: TOKEN, [ME]: { status: 200, body: STUDENT }, [ASK]: { status: 200, body: noCitations } });

    await ask(await signIn(), "What attendance do I need?");

    expect(await screen.findByRole("heading", { name: "Answer without citations" })).toBeInTheDocument();
    expect(screen.getAllByText("No citations attached").length).toBeGreaterThan(0);
    expect(screen.queryByText("Grounded answer")).not.toBeInTheDocument();
  });
});

describe("errors", () => {
  it("returns to sign-in when the session is rejected", async () => {
    mockApi({ [LOGIN]: TOKEN, [ME]: { status: 200, body: STUDENT }, [ASK]: { status: 401, body: { detail: "Could not validate credentials." } } });

    await ask(await signIn(), "What attendance do I need?");

    expect(await screen.findByText("Your session has ended. Please sign in again.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Know the rule. See the evidence." })).toBeInTheDocument();
  });

  it("shows the cohort refusal and retries on request", async () => {
    mockApi({
      [LOGIN]: TOKEN,
      [ME]: { status: 200, body: STUDENT },
      [ASK]: [{ status: 403, body: { detail: "You can only access regulations for your own cohort." } }, { status: 200, body: ANSWERED }],
    });

    const user = await signIn();
    await ask(user, "What attendance do I need?");

    expect(await screen.findByText("This cohort isn't available to you")).toBeInTheDocument();
    expect(screen.getByText("You can only access regulations for your own cohort.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(ANSWERED.answer.answer)).toBeInTheDocument();
  });

  it("summarises validation errors", async () => {
    mockApi({
      [LOGIN]: TOKEN,
      [ME]: { status: 200, body: STUDENT },
      [ASK]: { status: 422, body: { detail: [{ type: "string_too_long", loc: ["body", "question"], msg: "String should have at most 2000 characters" }] } },
    });

    await ask(await signIn(), "Long question");

    expect(await screen.findByText("Please check your question")).toBeInTheDocument();
    expect(screen.getByText("String should have at most 2000 characters")).toBeInTheDocument();
  });

  it("shows the generic server message and handles network failures", async () => {
    mockApi({
      [LOGIN]: TOKEN,
      [ME]: { status: 200, body: STUDENT },
      [ASK]: [
        { status: 500, body: { detail: "The question could not be answered due to an internal server error. Please try again later." } },
        new TypeError("Failed to fetch"),
      ],
    });

    const user = await signIn();
    await ask(user, "What attendance do I need?");
    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText(/internal server error/)).toBeInTheDocument();

    await ask(user, "And again?");
    expect(await screen.findByText("Can't reach CohortIQ")).toBeInTheDocument();
  });

  it("cancels an in-flight question while preserving the typed text", async () => {
    const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
      if (url === "/api/v1/auth/login") {
        return new Response(JSON.stringify(TOKEN.body), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/auth/me") {
        return new Response(JSON.stringify(STUDENT), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/query/ask") {
        return new Promise<Response>((_, reject) => {
          init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        });
      }
      throw new Error(`Unexpected ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = await signIn();
    await ask(user, "What is the attendance rule?");
    // Both cancel buttons have distinct accessible names that keep the visible word "Cancel".
    const cancelRequest = await screen.findByRole("button", { name: "Cancel request" });
    expect(screen.getByRole("button", { name: "Cancel loading answer" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    await user.click(cancelRequest);

    expect(await screen.findByText("Request cancelled")).toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toHaveValue("What is the attendance rule?");
  });

  it("reports a timeout error when a request stalls past its client timeout", async () => {
    const { apiRequest, ApiError } = await import("./api/client");
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_, reject) => {
            init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
          }),
      ),
    );

    await expect(apiRequest("/api/v1/query/ask", { method: "POST", timeoutMs: 25 })).rejects.toSatisfy(
      (err: unknown) => err instanceof ApiError && err.kind === "timeout",
    );
  });
});

describe("cohort context", () => {
  it("blocks asking when a student's account has no cohort", async () => {
    const calls = mockApi({ [LOGIN]: TOKEN, [ME]: { status: 200, body: { ...STUDENT, admission_batch: null, programme: null } } });

    await signIn();

    expect(await screen.findByText("Your cohort isn't set")).toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    expect(calls.some((call) => call.url === "/api/v1/query/ask")).toBe(false);
  });

  it("lets an administrator preview a cohort", async () => {
    const calls = mockApi({ [LOGIN]: TOKEN, [ME]: { status: 200, body: ADMIN }, [ASK]: { status: 200, body: ANSWERED } });

    const user = await signIn(userEvent.setup(), "administrator");
    expect(await screen.findByText("Administrator")).toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toBeDisabled();
    await user.type(screen.getByLabelText("Admission batch"), "2024");
    await user.type(screen.getByLabelText("Programme"), "B-tech - CSE");
    await ask(user, "What attendance do I need?");

    await screen.findByText(ANSWERED.answer.answer);
    expect(calls.find((call) => call.url === "/api/v1/query/ask")!.body).toEqual({
      question: "What attendance do I need?",
      admission_batch: "2024",
      programme: "B-tech - CSE",
    });
  });
});

describe("session", () => {
  it("restores a stored session after checking it with the API", async () => {
    window.sessionStorage.setItem("cohortiq.session", JSON.stringify({ token: "stored", expiresAt: Date.now() + 600_000 }));
    const calls = mockApi({ [ME]: { status: 200, body: STUDENT } });

    renderApp();

    expect(await screen.findAllByText("Batch 2024")).not.toHaveLength(0);
    expect(calls[0]!.headers.Authorization).toBe("Bearer stored");
  });

  it("discards an expired stored session without calling the API", async () => {
    window.sessionStorage.setItem("cohortiq.session", JSON.stringify({ token: "old", expiresAt: Date.now() - 1000 }));
    const calls = mockApi({});

    renderApp();

    expect(await screen.findByRole("heading", { name: "Know the rule. See the evidence." })).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    expect(window.sessionStorage.getItem("cohortiq.session")).toBeNull();
  });

  it("signs out and clears the stored session", async () => {
    mockApi({ [LOGIN]: TOKEN, [ME]: { status: 200, body: STUDENT } });

    const user = await signIn();
    await screen.findAllByText("Batch 2024");
    expect(window.sessionStorage.getItem("cohortiq.session")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "Know the rule. See the evidence." })).toBeInTheDocument());
    expect(window.sessionStorage.getItem("cohortiq.session")).toBeNull();
  });
});

describe("public entry and role routing", () => {
  it("shows all three role choices and an existing-user sign-in link", async () => {
    renderApp();

    expect(await screen.findByRole("heading", { name: "Know the rule. See the evidence." })).toBeInTheDocument();
    for (const role of ["Student", "Staff / Teacher", "Administrator"]) {
      expect(screen.getByRole("heading", { name: role })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("button", { name: "Continue" })).toHaveLength(3);
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "#/signin");
    expect(screen.getAllByRole("link", { name: "Sign up" })[0]).toHaveAttribute("href", "#/signup");
    expect(screen.getAllByText(/What can I do here\?/)).toHaveLength(3);
  });

  it("opens student registration from the public Sign up link", async () => {
    mockApi({ [COHORTS]: AVAILABLE_COHORTS });
    renderApp();

    await userEvent.setup().click(screen.getAllByRole("link", { name: "Sign up" })[0]!);

    expect(await screen.findByRole("heading", { name: "Create student account" })).toBeInTheDocument();
    expect(screen.getByText("Selected role")).toBeInTheDocument();
    expect(screen.getByText("Student", { selector: ".selected-role strong" })).toBeInTheDocument();
  });

  it("compares versions, records applicability, and submits administrator review actions", async () => {
    const calls = mockApi({
      [LOGIN]: TOKEN,
      [ME]: { status: 200, body: ADMIN },
      "GET /api/v1/regulations": { status: 200, body: { regulations: CHANGE_RADAR_REGULATIONS } },
      "GET /api/v1/change-radar/reviews": [
        { status: 200, body: { reviews: [] } },
        { status: 200, body: { reviews: [CHANGE_REVIEW] } },
      ],
      "POST /api/v1/change-radar/reviews": { status: 201, body: CHANGE_REVIEW },
      "PATCH /api/v1/change-radar/reviews/11": {
        status: 200,
        body: { ...CHANGE_REVIEW, status: "approved", reviewed_by: 1, reviewed_at: "2026-01-11T09:00:00Z" },
      },
    });
    const user = userEvent.setup();
    await signIn(user, "administrator");
    await user.click(await screen.findByRole("link", { name: "Change Radar" }));
    await screen.findByRole("heading", { name: "Regulation Change Radar" });
    await user.selectOptions(screen.getByLabelText("Previous approved version"), "21");
    await user.selectOptions(screen.getByLabelText("Newly uploaded version"), "22");
    await user.click(screen.getByRole("button", { name: "Compare and save for review" }));

    expect(await screen.findByText("Comparison saved as Needs review. No regulation was published.")).toBeInTheDocument();
    expect(calls.find((call) => call.method === "POST" && call.url === "/api/v1/change-radar/reviews")?.body).toEqual({
      previous_regulation_id: 21,
      new_regulation_id: 22,
      applicable_batches: ["2024"],
      applicable_programmes: ["B-tech - CSE"],
    });
    await user.click(await screen.findByText("Academic Regulation", { selector: ".change-review summary strong" }));
    await user.click(await screen.findByRole("button", { name: "Approve reviewed changes" }));
    expect(await screen.findByText(/Review approved\. Students will see it only after the new regulation is also approved\./)).toBeInTheDocument();
    expect(calls.find((call) => call.method === "PATCH" && call.url === "/api/v1/change-radar/reviews/11")?.body).toEqual({
      status: "approved",
    });
  });

  it("routes an authenticated staff account to the staff workspace, not admin tools", async () => {
    const calls = mockApi({ [LOGIN]: TOKEN, [ME]: { status: 200, body: STAFF } });

    await signIn(userEvent.setup(), "staff");

    expect(screen.getByText("Staff / Teacher")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Regulations" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Audit Log" })).not.toBeInTheDocument();
    expect(calls[0]!.body).toMatchObject({
      email: "teacher@staff.smvec.ac.in",
      selected_role: "staff",
    });
  });

  it("does not offer public staff or administrator registration", async () => {
    const user = userEvent.setup();
    renderApp();

    const card = (await screen.findByRole("heading", { name: "Administrator" })).closest("article");
    if (!card) throw new Error("Missing administrator role card.");
    await user.click(within(card).getByRole("button", { name: "Continue" }));

    expect(screen.getByText(/public sign-up is unavailable/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create an account" })).not.toBeInTheDocument();
    expect(screen.getByText("Selected role")).toBeInTheDocument();
  });

  it("shows a clear denial when the backend rejects the selected role", async () => {
    mockApi({
      [LOGIN]: {
        status: 403,
        body: { detail: "Access denied. This account does not match the selected role or permitted email domain." },
      },
    });

    await signIn();

    expect(await screen.findByText(/Access denied\. This account does not match the selected role/)).toBeInTheDocument();
    expect(window.sessionStorage.getItem("cohortiq.session")).toBeNull();
  });
});

describe("registration", () => {
  const REGISTER = "POST /api/v1/auth/register";

  async function openRegistration() {
    const user = userEvent.setup();
    renderApp();
    const card = (await screen.findByRole("heading", { name: "Student" })).closest("article");
    if (!card) throw new Error("Missing student role card.");
    await user.click(within(card).getByRole("button", { name: "Continue" }));
    await user.click(await screen.findByRole("button", { name: "Create an account" }));
    expect(screen.getByRole("heading", { name: "Create student account" })).toBeInTheDocument();
    return user;
  }

  async function fill(user: ReturnType<typeof userEvent.setup>, email: string) {
    await user.type(screen.getByLabelText("Full name (optional)"), "Asha Kumar");
    await user.type(screen.getByLabelText("Student email"), email);
    await user.type(screen.getByLabelText("Password"), "Campus-Rules-2024!");
    await user.selectOptions(screen.getByRole("combobox", { name: "Cohort" }), "0");
    await user.click(screen.getByRole("button", { name: "Create account" }));
  }

  it("registers a student, then signs in and opens the workspace", async () => {
    const calls = mockApi({
      [COHORTS]: AVAILABLE_COHORTS,
      [REGISTER]: { status: 201, body: { ...STUDENT, email: "asha@student.smvec.ac.in" } },
      [LOGIN]: TOKEN,
      [ME]: { status: 200, body: STUDENT },
    });

    const user = await openRegistration();
    await fill(user, "Asha@Student.SMVEC.ac.in");

    expect(await screen.findAllByText("Batch 2024")).not.toHaveLength(0);
    const registration = calls.find((call) => call.url === "/api/v1/auth/register")!;
    expect(registration).toMatchObject({
      url: "/api/v1/auth/register",
      body: {
        email: "asha@student.smvec.ac.in",
        password: "Campus-Rules-2024!",
        admission_batch: "2024",
        programme: "B-tech - CSE",
        full_name: "Asha Kumar",
      },
    });
    expect(registration.body).not.toHaveProperty("role");
    expect(calls.find((call) => call.url === "/api/v1/auth/login")).toMatchObject({
      url: "/api/v1/auth/login",
      body: { email: "asha@student.smvec.ac.in", selected_role: "student" },
    });
  });

  it("rejects other email domains before calling the API", async () => {
    const calls = mockApi({ [COHORTS]: AVAILABLE_COHORTS });

    const user = await openRegistration();
    await fill(user, "asha@gmail.com");

    expect(await screen.findByText("Use your student email address ending in @student.smvec.ac.in.")).toBeInTheDocument();
    expect(calls.some((call) => call.url === "/api/v1/auth/register")).toBe(false);
  });

  it("offers sign-in when the account already exists", async () => {
    mockApi({
      [COHORTS]: AVAILABLE_COHORTS,
      [REGISTER]: { status: 409, body: { detail: "An account with this email already exists. Please sign in instead." } },
    });

    const user = await openRegistration();
    await fill(user, "asha@student.smvec.ac.in");

    expect(await screen.findByText(/already exists/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Go to sign in" }));
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows the API's password-policy message", async () => {
    mockApi({
      [COHORTS]: AVAILABLE_COHORTS,
      [REGISTER]: {
        status: 422,
        body: { detail: [{ type: "value_error", loc: ["body", "password"], msg: "Password does not meet the password policy: Use at least 12 characters." }] },
      },
    });

    const user = await openRegistration();
    await fill(user, "asha@student.smvec.ac.in");

    expect(await screen.findByText(/Use at least 12 characters/)).toBeInTheDocument();
  });

  it("shows a retryable cohort-list error and recovers when the API responds", async () => {
    mockApi({
      [COHORTS]: [
        { status: 404, body: { detail: "Not found" } },
        AVAILABLE_COHORTS,
      ],
    });

    const user = await openRegistration();
    expect(await screen.findByRole("alert")).toHaveTextContent("Available cohorts could not be loaded");
    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("combobox", { name: "Cohort" })).toHaveTextContent("Batch 2024 · B-tech - CSE");
  });
});
