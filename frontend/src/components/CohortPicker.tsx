import { useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { fetchCohorts } from "../api/cohortiq";
import type { Cohort } from "../api/types";
import { Notice } from "./Notice";

interface CohortResource {
  cohorts: Cohort[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/** Cohorts covered by approved regulations, with an explicit retryable failure state. */
export function useCohorts(enabled = true): CohortResource {
  const [cohorts, setCohorts] = useState<Cohort[]>([]);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchCohorts(controller.signal)
      .then((list) => {
        setCohorts(Array.isArray(list) ? list : []);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          caught instanceof ApiError
            ? caught.message
            : "The cohort list could not be loaded. You can enter the values manually or retry.",
        );
        setLoading(false);
      });
    return () => controller.abort();
  }, [enabled, attempt]);

  return { cohorts, loading, error, reload: () => setAttempt((value) => value + 1) };
}

const OTHER = "other";

/**
 * Choose an exact admission batch and programme. Retrieval matches these strings
 * exactly, so a list of known cohorts prevents mismatches; typing is still
 * possible for a cohort that has no approved regulation yet.
 */
export function CohortPicker({
  cohorts,
  loading = false,
  error,
  onRetry,
  batch,
  programme,
  onChange,
}: {
  cohorts: Cohort[];
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  batch: string;
  programme: string;
  onChange: (batch: string, programme: string) => void;
}) {
  const [custom, setCustom] = useState(false);
  const selected = cohorts.findIndex((c) => c.admission_batch === batch && c.programme === programme);
  const manual = !cohorts.length || custom || (selected < 0 && Boolean(batch || programme));

  return (
    <>
      {loading ? (
        <p className="field__hint" role="status">
          Loading available cohorts…
        </p>
      ) : null}
      {error ? (
        <Notice
          tone="error"
          title="Available cohorts could not be loaded"
          action={
            onRetry ? (
              <button type="button" className="button button--ghost button--compact" onClick={onRetry}>
                Retry
              </button>
            ) : undefined
          }
        >
          {error} You may enter your batch and programme manually, but they must match the applicable regulation metadata.
        </Notice>
      ) : null}
      {!loading && !error && !cohorts.length ? (
        <p className="field__hint" role="status">
          No applicable cohorts were returned. You can still enter your batch and programme manually.
        </p>
      ) : null}
      {cohorts.length ? (
        <label className="field">
          <span>Cohort</span>
          <select
            value={manual ? (custom || batch || programme ? OTHER : "") : selected < 0 ? "" : String(selected)}
            onChange={(event) => {
              const value = event.target.value;
              setCustom(value === OTHER);
              const cohort = value === OTHER || value === "" ? undefined : cohorts[Number(value)];
              onChange(cohort?.admission_batch ?? "", cohort?.programme ?? "");
            }}
          >
            <option value="">Choose your batch and programme</option>
            {cohorts.map((cohort, index) => (
              <option key={`${cohort.admission_batch}|${cohort.programme}`} value={String(index)}>
                Batch {cohort.admission_batch} · {cohort.programme}
              </option>
            ))}
            <option value={OTHER}>Not listed (type it)</option>
          </select>
        </label>
      ) : null}
      {manual ? (
        <div className="field-row">
          <label className="field">
            <span>Admission batch</span>
            <input
              value={batch}
              onChange={(event) => onChange(event.target.value, programme)}
              placeholder="e.g. 2024"
              maxLength={100}
              required
            />
          </label>
          <label className="field">
            <span>Programme</span>
            <input
              value={programme}
              onChange={(event) => onChange(batch, event.target.value)}
              placeholder="e.g. B-tech - CSE"
              maxLength={100}
              required
            />
          </label>
        </div>
      ) : null}
    </>
  );
}
