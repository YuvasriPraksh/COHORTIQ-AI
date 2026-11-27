import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { ApiError, type ApiErrorKind } from "../api/client";
import { askQuestion } from "../api/cohortiq";
import { MAX_QUESTION_LENGTH, type UserProfile } from "../api/types";
import { useSession } from "../auth/session";
import { AnswerView, type AnswerState } from "./AnswerView";
import { Notice } from "./Notice";

const SUGGESTIONS = [
  "What is the minimum attendance needed to write the end semester exam?",
  "What are the conditions for First Class with Distinction?",
  "Who is eligible to apply for revaluation?",
];

const ERROR_TITLES: Record<Exclude<ApiErrorKind, "unauthorized">, string> = {
  forbidden: "This cohort isn't available to you",
  invalid: "Please check your question",
  too_large: "Your question is too long",
  unavailable: "CohortIQ is temporarily unavailable",
  network: "Can't reach CohortIQ",
  server: "Something went wrong",
};

export function AskWorkspace({ token, user }: { token: string; user: UserProfile }) {
  const { handleUnauthorized } = useSession();
  const isStudent = user.role === "student";
  const [batch, setBatch] = useState(isStudent ? user.admission_batch ?? "" : "");
  const [programme, setProgramme] = useState(isStudent ? user.programme ?? "" : "");
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<AnswerState>({ kind: "idle" });
  const lastQuestion = useRef("");
  const inFlight = useRef<AbortController | null>(null);
  const questionId = useId();
  const hintId = useId();

  useEffect(() => () => inFlight.current?.abort(), []);

  const hasCohort = Boolean(batch.trim() && programme.trim());
  const trimmed = question.trim();
  const loading = state.kind === "loading";
  const canAsk = hasCohort && trimmed.length > 0 && !loading;

  async function submit(text: string) {
    if (!text || !hasCohort) return;
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    lastQuestion.current = text;
    setState({ kind: "loading", question: text });
    try {
      const response = await askQuestion(
        token,
        { question: text, admission_batch: batch.trim(), programme: programme.trim() },
        controller.signal,
      );
      setState({ kind: "result", question: text, response });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (error instanceof ApiError && error.kind === "unauthorized") {
        handleUnauthorized();
        return;
      }
      const kind = error instanceof ApiError ? error.kind : "server";
      const message = error instanceof ApiError ? error.message : "Please try again later.";
      setState({ kind: "error", question: text, title: ERROR_TITLES[kind as keyof typeof ERROR_TITLES], message });
    } finally {
      if (inFlight.current === controller) inFlight.current = null;
    }
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
        <h1 id="ask-heading" className="ask__title">
          What would you like to know?
        </h1>

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
              {question.length}/{MAX_QUESTION_LENGTH} · Ctrl + Enter to ask
            </span>
            <button type="submit" className="button button--primary" disabled={!canAsk}>
              {loading ? <span className="spinner" aria-hidden="true" /> : null}
              {loading ? "Asking…" : "Ask"}
            </button>
          </div>
        </form>

        {hasCohort ? (
          <div className="suggestions" aria-label="Example questions">
            {SUGGESTIONS.map((suggestion) => (
              <button key={suggestion} type="button" className="suggestion" onClick={() => setQuestion(suggestion)}>
                {suggestion}
              </button>
            ))}
          </div>
        ) : null}
      </section>

      <section className="panel result" aria-live="polite">
        <AnswerView state={state} onRetry={() => void submit(lastQuestion.current)} />
      </section>
    </div>
  );
}
