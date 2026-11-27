import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { ApiError, type ApiErrorKind } from "../api/client";
import { askQuestion } from "../api/cohortiq";
import { MAX_QUESTION_LENGTH, type ChunkingStrategy, type UserProfile } from "../api/types";
import { useSession } from "../auth/session";
import { useHistory } from "../state/history";
import { resolveAnswerVerdict } from "../utils/answerFormatting";
import { AnswerView, type AnswerState } from "./AnswerView";
import { Notice } from "./Notice";

const SUGGESTIONS = [
  "What is the minimum attendance needed to write the end semester examination?",
  "What does clause 10.1 say about appearing for the end semester examination?",
  "What are the conditions for First Class with Distinction?",
];

const ERROR_TITLES: Record<Exclude<ApiErrorKind, "unauthorized">, string> = {
  not_found: "That wasn't found",
  conflict: "Please try again",
  forbidden: "This cohort isn't available to you",
  invalid: "Please check your question",
  too_large: "Your question is too long",
  timeout: "CohortIQ timed out",
  unavailable: "CohortIQ is temporarily unavailable",
  network: "Can't reach CohortIQ",
  server: "Something went wrong",
};

function shortHint(): string {
  if (typeof navigator !== "undefined" && /Mac|iPhone|iPad/i.test(navigator.platform || "")) {
    return "Cmd + Enter to ask";
  }
  return "Ctrl + Enter to ask";
}

export function AskWorkspace({ token, user }: { token: string; user: UserProfile }) {
  const { handleUnauthorized } = useSession();
  const { entries, activeId, add, select, clear, draft, setDraft } = useHistory();
  const isStudent = user.role === "student";
  const [batch, setBatch] = useState(isStudent ? user.admission_batch ?? "" : "");
  const [programme, setProgramme] = useState(isStudent ? user.programme ?? "" : "");
  const [question, setQuestion] = useState(draft);
  const [chunkingStrategy, setChunkingStrategy] = useState<ChunkingStrategy>("recursive");
  const [state, setState] = useState<AnswerState>({ kind: "idle" });
  const lastQuestion = useRef("");
  const inFlight = useRef<AbortController | null>(null);
  const resultRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const questionId = useId();
  const hintId = useId();

  useEffect(() => () => inFlight.current?.abort(), []);

  useEffect(() => {
    setDraft(question);
  }, [question, setDraft]);

  const activeEntry = activeId != null ? entries.find((entry) => entry.id === activeId) : undefined;
  const displayedState: AnswerState =
    state.kind === "loading" || state.kind === "cancelled" || state.kind === "error"
      ? state
      : activeEntry
        ? { kind: "result", question: activeEntry.question, response: activeEntry.response }
        : state;

  const hasCohort = Boolean(batch.trim() && programme.trim());
  const trimmed = question.trim();
  const loading = state.kind === "loading";
  const canAsk = hasCohort && trimmed.length > 0 && !loading;

  function scrollResultIfStacked() {
    if (typeof window !== "undefined" && window.matchMedia?.("(max-width: 959px)").matches) {
      resultRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    }
  }

  async function submit(text: string) {
    if (!text || !hasCohort) return;
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    lastQuestion.current = text;
    setState({ kind: "loading", question: text });
    try {
      const cohort = { admission_batch: batch.trim(), programme: programme.trim() };
      const response = await askQuestion(
        token,
        {
          question: text,
          ...cohort,
          ...(chunkingStrategy !== "recursive" ? { chunking_strategy: chunkingStrategy } : {}),
        },
        controller.signal,
      );
      add(text, cohort, response);
      setState({ kind: "result", question: text, response });
      scrollResultIfStacked();
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (error instanceof ApiError && error.kind === "unauthorized") {
        handleUnauthorized();
        return;
      }
      const kind = error instanceof ApiError ? error.kind : "server";
      const message = error instanceof ApiError ? error.message : "Please try again later.";
      setState({ kind: "error", question: text, title: ERROR_TITLES[kind as keyof typeof ERROR_TITLES], message });
      scrollResultIfStacked();
    } finally {
      if (inFlight.current === controller) inFlight.current = null;
    }
  }

  function cancelInFlight() {
    if (!inFlight.current) return;
    inFlight.current.abort();
    inFlight.current = null;
    setState({ kind: "cancelled", question: lastQuestion.current });
  }

  function startNewQuestion() {
    inFlight.current?.abort();
    inFlight.current = null;
    select(null);
    setState({ kind: "idle" });
    setQuestion("");
    inputRef.current?.focus();
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void submit(trimmed);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && canAsk) {
      event.preventDefault();
      void submit(trimmed);
    }
  }

  return (
    <div className="workspace">
      <section className="panel ask" aria-labelledby="ask-heading">
        <div className="ask__head">
          <h1 id="ask-heading" className="ask__title">
            What would you like to know?
          </h1>
          {question || entries.length ? (
            <button type="button" className="link-button" onClick={startNewQuestion}>
              New question
            </button>
          ) : null}
        </div>

        <div className="cohort" aria-label="Cohort used for your question">
          {isStudent ? (
            hasCohort ? (
              <>
                <span className="cohort__label">Your cohort</span>
                <span className="chip">Batch {batch}</span>
                <span className="chip">{programme}</span>
              </>
            ) : (
              <Notice tone="warning" title="Your cohort isn't set">
                Answers depend on your admission batch and programme, and your account doesn't have them yet. Please
                ask your administrator to add them.
              </Notice>
            )
          ) : (
            <fieldset className="cohort__preview">
              <legend>Preview as a cohort</legend>
              <label>
                <span>Admission batch</span>
                <input value={batch} onChange={(e) => setBatch(e.target.value)} maxLength={100} placeholder="e.g. 2024" />
              </label>
              <label>
                <span>Programme</span>
                <input
                  value={programme}
                  onChange={(e) => setProgramme(e.target.value)}
                  maxLength={100}
                  placeholder="e.g. B-tech - CSE"
                />
              </label>
            </fieldset>
          )}
        </div>

        <form onSubmit={onSubmit} className="ask__form">
          <label htmlFor={questionId} className="visually-hidden">
            Your question
          </label>
          <textarea
            ref={inputRef}
            id={questionId}
            className="ask__input"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onKeyDown}
            maxLength={MAX_QUESTION_LENGTH}
            rows={4}
            placeholder="Ask about attendance, exams, grading, credits…"
            aria-describedby={hintId}
            disabled={!hasCohort}
          />
          <div className="ask__footer">
            <span id={hintId} className="ask__hint">
              {question.length}/{MAX_QUESTION_LENGTH} · {shortHint()}
            </span>
            <div className="ask__actions">
              {loading ? (
                <button
                  type="button"
                  className="button button--ghost"
                  onClick={cancelInFlight}
                  aria-label="Cancel request"
                >
                  Cancel
                </button>
              ) : null}
              <button type="submit" className="button button--primary" disabled={!canAsk}>
                {loading ? <span className="spinner" aria-hidden="true" /> : null}
                {loading ? "Asking…" : "Ask"}
              </button>
            </div>
          </div>

          {hasCohort ? (
            <details className="ask__options">
              <summary>Retrieval chunking ({chunkingStrategy})</summary>
              <label className="ask__strategy">
                <span>Chunking strategy</span>
                <select
                  value={chunkingStrategy}
                  onChange={(e) => setChunkingStrategy(e.target.value as ChunkingStrategy)}
                >
                  <option value="recursive">Recursive (default)</option>
                  <option value="fixed_size">Fixed size</option>
                  <option value="semantic">Semantic</option>
                </select>
              </label>
            </details>
          ) : null}
        </form>

        {hasCohort ? (
          <div className="suggestions" aria-label="Example questions">
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                className="suggestion"
                onClick={() => {
                  setQuestion(suggestion);
                  inputRef.current?.focus();
                }}
              >
                {suggestion}
              </button>
            ))}
          </div>
        ) : null}

        {entries.length > 0 ? (
          <section className="history" aria-label="Recent questions in this session">
            <div className="history__head">
              <h2 className="history__title">
                Session history <span className="count">{entries.length}</span>
              </h2>
              <button type="button" className="link-button" onClick={() => { clear(); setState({ kind: "idle" }); }}>
                Clear
              </button>
            </div>
            <ul className="history__list">
              {entries.map((entry) => {
                const verdict = resolveAnswerVerdict(entry.response);
                const selected = displayedState.kind === "result" && activeId === entry.id;
                return (
                  <li key={entry.id}>
                    <button
                      type="button"
                      className={`history__item${selected ? " history__item--active" : ""}`}
                      onClick={() => {
                        select(entry.id);
                        setState({ kind: "result", question: entry.question, response: entry.response });
                        setQuestion(entry.question);
                      }}
                    >
                      <span className="history__q">{entry.question}</span>
                      <span className={`verdict verdict--${verdict.tone}`}>{verdict.badge}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}
      </section>

      <section ref={resultRef} className="panel result">
        <AnswerView
          token={token}
          state={displayedState}
          onRetry={() => void submit(lastQuestion.current || trimmed)}
          onCancel={cancelInFlight}
        />
      </section>
    </div>
  );
}
