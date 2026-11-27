import { useEffect, useRef } from "react";

import type { AskResponse } from "../api/types";
import { formatValidationMessaging, resolveAnswerVerdict } from "../utils/answerFormatting";
import { Citations, SourcesSearched } from "./Evidence";
import { Notice } from "./Notice";
import { RouteBadge } from "./RouteBadge";

export type AnswerState =
  | { kind: "idle" }
  | { kind: "loading"; question: string }
  | { kind: "cancelled"; question: string }
  | { kind: "error"; question: string; title: string; message: string }
  | { kind: "result"; question: string; response: AskResponse };

export function AnswerView({
  state,
  onRetry,
  onCancel,
}: {
  state: AnswerState;
  onRetry: () => void;
  onCancel: () => void;
}) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const cancelledRef = useRef<HTMLDivElement>(null);

  // Move focus cleanly once on terminal states; loading relies on its status region.
  useEffect(() => {
    if (state.kind === "result") headingRef.current?.focus();
    if (state.kind === "error") errorRef.current?.focus();
    if (state.kind === "cancelled") cancelledRef.current?.focus();
  }, [state]);

  if (state.kind === "idle") {
    return (
      <div className="empty">
        <div className="empty__art" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <h2 className="empty__title">Ask about your regulations</h2>
        <p className="empty__text">
          Answers come only from the approved regulations for your cohort, with the pages they rely on.
        </p>
        <ul className="empty__pillars" aria-label="How CohortIQ answers">
          <li>Scoped to your admission batch and programme</li>
          <li>Drawn only from administrator-approved documents</li>
          <li>Abstains plainly when evidence is missing</li>
        </ul>
      </div>
    );
  }

  if (state.kind === "loading") {
    return (
      <div className="answer answer--loading" aria-busy="true">
        <p className="answer__question">{state.question}</p>
        <div className="loading-bar">
          <p className="loading-text" role="status" aria-live="polite">
            Finding the approved regulations that apply to you…
          </p>
          <button
            type="button"
            className="button button--ghost button--compact"
            onClick={onCancel}
            aria-label="Cancel loading answer"
          >
            Cancel
          </button>
        </div>
        <div className="skeleton" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </div>
    );
  }

  if (state.kind === "cancelled") {
    return (
      <div className="answer answer--cancelled" ref={cancelledRef} tabIndex={-1}>
        <p className="answer__question">{state.question}</p>
        <Notice
          tone="info"
          title="Request cancelled"
          action={
            <button type="button" className="button button--ghost" onClick={onRetry}>
              Ask again
            </button>
          }
        >
          Your question is still in the box if you want to edit or send it again.
        </Notice>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="answer answer--error" ref={errorRef} tabIndex={-1}>
        <p className="answer__question">{state.question}</p>
        <Notice
          tone="error"
          title={state.title}
          action={
            <button type="button" className="button button--ghost" onClick={onRetry}>
              Try again
            </button>
          }
        >
          {state.message}
        </Notice>
      </div>
    );
  }

  const { response } = state;
  const verdict = resolveAnswerVerdict(response);
  const validation = formatValidationMessaging(
    response.answer.limitations,
    response.validation_issues,
    response.status,
  );

  return (
    <article className={`answer answer--${verdict.tone}`} aria-labelledby="answer-heading">
      <p className="answer__question">{state.question}</p>
      <div className="answer__head">
        <div className="answer__title-row">
          <h2 id="answer-heading" ref={headingRef} tabIndex={-1} className="answer__title">
            {verdict.title}
          </h2>
          <span className={`verdict verdict--${verdict.tone}`}>{verdict.badge}</span>
        </div>
        {response.route ? (
          <RouteBadge
            route={response.route}
            answerStatus={response.status}
            hasCitations={verdict.hasCitations}
          />
        ) : null}
      </div>
      <p className="answer__text">{response.answer.answer}</p>
      {validation.limitationNote ? (
        <p className="answer__limitations">
          <strong>Note: </strong>
          {validation.limitationNote}
        </p>
      ) : null}
      {validation.issues.length ? (
        <Notice tone="warning" title={validation.issuesTitle}>
          <ul className="plain-list">
            {validation.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </Notice>
      ) : null}
      <Citations citations={response.citations} />
      <SourcesSearched results={response.retrieval.results} />
    </article>
  );
}
