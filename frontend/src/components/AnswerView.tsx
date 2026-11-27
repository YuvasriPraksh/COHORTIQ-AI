import { useEffect, useRef } from "react";

import type { AskResponse } from "../api/types";
import { Citations, SourcesSearched } from "./Evidence";
import { Notice } from "./Notice";
import { RouteBadge } from "./RouteBadge";

export type AnswerState =
  | { kind: "idle" }
  | { kind: "loading"; question: string }
  | { kind: "error"; question: string; title: string; message: string }
  | { kind: "result"; question: string; response: AskResponse };

const STATUS_COPY: Record<string, { title: string; tone: "answered" | "abstained" | "conflict" }> = {
  answered: { title: "Answer", tone: "answered" },
  insufficient_evidence: { title: "No grounded answer", tone: "abstained" },
  conflicting_evidence: { title: "The regulations disagree", tone: "conflict" },
};

function titleFor(response: AskResponse): string {
  if (response.route?.route === "out_of_scope") return "Outside what I can answer";
  if (response.route?.route === "clarify") return "I need your cohort first";
  return (STATUS_COPY[response.status] ?? STATUS_COPY.insufficient_evidence!).title;
}

export function AnswerView({ state, onRetry }: { state: AnswerState; onRetry: () => void }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);

  // Move focus to the new answer or error so keyboard and screen-reader users land on it.
  useEffect(() => {
    if (state.kind === "result") headingRef.current?.focus();
    if (state.kind === "error") errorRef.current?.focus();
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
      </div>
    );
  }

  if (state.kind === "loading") {
    return (
      <div className="answer answer--loading" aria-busy="true">
        <p className="answer__question">{state.question}</p>
        <p className="loading-text" role="status">
          Finding the regulations that apply to you…
        </p>
        <div className="skeleton" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
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
  const tone = (STATUS_COPY[response.status] ?? STATUS_COPY.insufficient_evidence!).tone;
  const limitations = response.answer.limitations;

  return (
    <article className={`answer answer--${tone}`} aria-labelledby="answer-heading">
      <p className="answer__question">{state.question}</p>
      <div className="answer__head">
        <h2 id="answer-heading" ref={headingRef} tabIndex={-1} className="answer__title">
          {titleFor(response)}
        </h2>
        {response.route ? <RouteBadge route={response.route} /> : null}
      </div>
      <p className="answer__text">{response.answer.answer}</p>
      {limitations ? (
        <p className="answer__limitations">
          <strong>Note: </strong>
          {limitations}
        </p>
      ) : null}
      {response.validation_issues.length ? (
        <Notice tone="warning" title="Some citations were removed">
          <ul className="plain-list">
            {response.validation_issues.map((issue) => (
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
