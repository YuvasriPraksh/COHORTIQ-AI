import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AskResponse, UserProfile } from "./api/types";
import { SessionProvider } from "./auth/session";

// ---------------------------------------------------------------------------
// Fixtures shaped exactly like the API responses
// ---------------------------------------------------------------------------

const STUDENT: UserProfile = {
  id: 7,
  email: "asha@uni.edu",
  role: "student",
  full_name: "Asha Kumar",
  admission_batch: "2024",
  programme: "B-tech - CSE",
  is_active: true,
  created_at: "2026-01-10T09:00:00Z",
};

const ADMIN: UserProfile = { ...STUDENT, id: 1, role: "administrator", full_name: null, email: "admin@uni.edu", admission_batch: null, programme: null };

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
const TOKEN = { status: 200, body: { access_token: "token-abc", token_type: "bearer", expires_in: 1800 } };

function renderApp() {
  return render(
    <SessionProvider>
      <App />
    </SessionProvider>,
  );
}

async function signIn(user = userEvent.setup()) {
  renderApp();
  await user.type(await screen.findByLabelText("Email"), "asha@uni.edu");
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
    expect(await screen.findByText("Batch 2024")).toBeInTheDocument();
    expect(screen.getByText("B-tech - CSE")).toBeInTheDocument();
    await ask(user, "What attendance do I need?");

    expect(await screen.findByRole("heading", { name: "Answer" })).toHaveFocus();
    expect(screen.getByText(ANSWERED.answer.answer)).toBeInTheDocument();
    expect(screen.getByText("Searched your regulations")).toBeInTheDocument();
    const evidence = screen.getByRole("region", { name: /Evidence/ });
    expect(within(evidence).getByText(/SMVEC · version 2023/)).toBeInTheDocument();
    expect(within(evidence).getByText(/page 21/)).toBeInTheDocument();
    expect(within(evidence).getByText(ANSWERED.citations[0]!.relevant_supporting_text!)).toBeInTheDocument();
    expect(screen.getByText("Passages searched")).toBeInTheDocument();

    expect(calls[0]).toMatchObject({ url: "/api/v1/auth/login", body: { email: "asha@uni.edu", password: "Correct-horse-9" } });
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
});

describe("errors", () => {
  it("returns to sign-in when the session is rejected", async () => {
    mockApi({ [LOGIN]: TOKEN, [ME]: { status: 200, body: STUDENT }, [ASK]: { status: 401, body: { detail: "Could not validate credentials." } } });

    await ask(await signIn(), "What attendance do I need?");

    expect(await screen.findByText("Your session has ended. Please sign in again.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
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

    const user = await signIn();
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

    expect(await screen.findByText("Batch 2024")).toBeInTheDocument();
    expect(calls[0]!.headers.Authorization).toBe("Bearer stored");
  });

  it("discards an expired stored session without calling the API", async () => {
    window.sessionStorage.setItem("cohortiq.session", JSON.stringify({ token: "old", expiresAt: Date.now() - 1000 }));
    const calls = mockApi({});

    renderApp();

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    expect(window.sessionStorage.getItem("cohortiq.session")).toBeNull();
  });

  it("signs out and clears the stored session", async () => {
    mockApi({ [LOGIN]: TOKEN, [ME]: { status: 200, body: STUDENT } });

    const user = await signIn();
    await screen.findByText("Batch 2024");
    expect(window.sessionStorage.getItem("cohortiq.session")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument());
    expect(window.sessionStorage.getItem("cohortiq.session")).toBeNull();
  });
});
