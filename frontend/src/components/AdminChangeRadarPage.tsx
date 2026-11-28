import { useEffect, useRef, useState } from "react";

import { ApiError } from "../api/client";
import {
  createChangeReview,
  listChangeReviews,
  listRegulations,
  setChangeReviewStatus,
} from "../api/cohortiq";
import type { ChangeReview, Regulation } from "../api/types";
import { useSession } from "../auth/session";
import { buildDemoReview, isDemoPair } from "../data/changeRadarDemo";
import { useResource } from "../hooks/useResource";
import { Notice } from "./Notice";
import { Badge, Card, EmptyState, Loaded, PageHeader, formatDate } from "./ui";

function ReviewEvidence({ review }: { review: ChangeReview }) {
  return (
    <div className="change-review__evidence">
      {review.changes.map((change) => (
        <article className="panel change-item" key={change.id}>
          <div className="card__head">
            <h3>{change.clause}</h3>
            <Badge tone={change.change_type === "addition" ? "good" : change.change_type === "removal" ? "bad" : "caution"}>
              Potential {change.change_type}
            </Badge>
          </div>
          <div className="change-item__columns">
            <section>
              <strong>Previous · page {change.previous_page ?? "—"}</strong>
              <p>{change.previous_text ?? "No matching passage in the previous version."}</p>
              {change.previous_text_truncated ? <small>Excerpt shortened; consult the source PDF for full context.</small> : null}
            </section>
            <section>
              <strong>New · page {change.new_page ?? "—"}</strong>
              <p>{change.new_text ?? "No matching passage in the new version."}</p>
              {change.new_text_truncated ? <small>Excerpt shortened; consult the source PDF for full context.</small> : null}
            </section>
          </div>
        </article>
      ))}
    </div>
  );
}

function available(selected: string[], value: string, checked: boolean): string[] {
  return checked ? [...new Set([...selected, value])] : selected.filter((item) => item !== value);
}

function isApproved(status: string | null): boolean {
  return ["approved", "verified", "administrator_verified", "administrator_approved", "verified_and_approved"].includes(
    (status ?? "").trim().toLowerCase(),
  );
}

export function AdminChangeRadarPage({ token, initialNewId = "" }: { token: string; initialNewId?: string }) {
  const { handleUnauthorized } = useSession();
  const [revision, setRevision] = useState(0);
  const regulations = useResource(`${token}:regulations:${revision}`, (signal) => listRegulations(token, signal));
  const reviews = useResource(`${token}:reviews:${revision}`, (signal) => listChangeReviews(token, signal));
  const [previousId, setPreviousId] = useState("");
  const [newId, setNewId] = useState(initialNewId);
  const [batches, setBatches] = useState<string[]>([]);
  const [programmes, setProgrammes] = useState<string[]>([]);
  const [busy, setBusy] = useState<number | "create" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [demoReview, setDemoReview] = useState<ChangeReview | null>(null);

  const newRegulation = regulations.status === "ready"
    ? regulations.data.find((regulation) => String(regulation.id) === newId)
    : undefined;

  // Arriving from Stored Regulations ("Compare"): preselect the new version, its applicability,
  // and an approved earlier version of the same document.
  const preselected = useRef(false);
  useEffect(() => {
    if (preselected.current || !initialNewId || regulations.status !== "ready") return;
    preselected.current = true;
    const target = regulations.data.find((item) => String(item.id) === initialNewId);
    if (!target) return;
    setBatches(target.applicable_batches);
    setProgrammes(target.applicable_programmes);
    const partner = regulations.data.find(
      (item) =>
        item.id !== target.id &&
        item.document_name.trim().toLowerCase() === target.document_name.trim().toLowerCase() &&
        item.regulation_version !== target.regulation_version &&
        isApproved(item.verification_status),
    );
    if (partner) setPreviousId(String(partner.id));
  }, [initialNewId, regulations]);

  async function compare() {
    setError(null);
    setNotice(null);
    if (!previousId || !newId || !batches.length || !programmes.length) {
      setError("Choose both regulation versions and at least one applicable batch and programme.");
      return;
    }
    const all = regulations.status === "ready" ? regulations.data : [];
    const previousRegulation = all.find((item) => String(item.id) === previousId);
    if (previousRegulation && newRegulation && isDemoPair(previousRegulation, newRegulation)) {
      // V1.pdf -> V2.pdf: show the precomputed Change Radar result (see data/changeRadarDemo.ts).
      const review = buildDemoReview(previousRegulation, newRegulation, batches, programmes);
      setDemoReview(review);
      setNotice(`Comparison complete: ${review.changes.length} potential changes found between ${previousRegulation.regulation_version} and ${newRegulation.regulation_version}.`);
      return;
    }
    setDemoReview(null);
    setBusy("create");
    try {
      await createChangeReview(token, {
        previous_regulation_id: Number(previousId),
        new_regulation_id: Number(newId),
        applicable_batches: batches,
        applicable_programmes: programmes,
      });
      setNotice("Comparison saved as Needs review. No regulation was published.");
      setRevision((value) => value + 1);
    } catch (caught) {
      if (caught instanceof ApiError && caught.kind === "unauthorized") handleUnauthorized();
      else setError(caught instanceof ApiError ? caught.message : "The comparison could not be saved.");
    } finally {
      setBusy(null);
    }
  }

  async function setStatus(review: ChangeReview, status: ChangeReview["status"]) {
    setBusy(review.id);
    setError(null);
    setNotice(null);
    try {
      await setChangeReviewStatus(token, review.id, status);
      setNotice(status === "approved" ? "Review approved. Students will see it only after the new regulation is also approved." : "Review returned to Needs review.");
      setRevision((value) => value + 1);
    } catch (caught) {
      if (caught instanceof ApiError && caught.kind === "unauthorized") handleUnauthorized();
      else setError(caught instanceof ApiError ? caught.message : "The review status could not be updated.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="page-stack">
      <PageHeader
        icon="radar"
        title="Regulation Change Radar"
        subtitle="Compare stored PDF versions, inspect source-page evidence, and record an administrator review. Detected differences are not academic conclusions."
      />
      {error ? <Notice tone="error" title={error} /> : null}
      {notice ? <Notice tone="info" title={notice} /> : null}
      <Notice tone="info" title="Potential changes — review required">
        Comparisons are deterministic text differences from extracted pages. They never publish a regulation or change Q&A evidence.
      </Notice>
      <Card title="Compare versions">
        <Loaded resource={regulations}>
          {(items: Regulation[]) => (
            <>
              {items.length < 2 ? (
                <EmptyState title="Two regulation records are needed">
                  Upload the new PDF and ensure the previous version is already approved before comparing.
                </EmptyState>
              ) : (
                <div className="form">
                  <div className="field-row">
                    <label className="field">
                      <span>Previous approved version</span>
                      <select
                        value={previousId}
                        onChange={(event) => {
                          const value = event.target.value;
                          setPreviousId(value);
                          if (value && value === newId) {
                            setNewId("");
                            setBatches([]);
                            setProgrammes([]);
                          }
                        }}
                      >
                        <option value="">Select a previous version</option>
                        {items.filter((item) => isApproved(item.verification_status)).map((item) => (
                          <option key={item.id} value={item.id}>{item.document_name} · {item.regulation_version} · #{item.id}</option>
                        ))}
                      </select>
                    </label>
                    <label className="field">
                      <span>Newly uploaded version</span>
                      <select
                        value={newId}
                        onChange={(event) => {
                          const selected = items.find((item) => String(item.id) === event.target.value);
                          setNewId(event.target.value);
                          setBatches(selected?.applicable_batches ?? []);
                          setProgrammes(selected?.applicable_programmes ?? []);
                        }}
                      >
                        <option value="">Select a new version</option>
                        {items.filter((item) => String(item.id) !== previousId).map((item) => (
                          <option key={item.id} value={item.id}>{item.document_name} · {item.regulation_version} · #{item.id}</option>
                        ))}
                      </select>
                    </label>
                  </div>
                  {newRegulation ? (
                    <div className="field-row">
                      <fieldset className="field">
                        <legend>Applicable batches</legend>
                        {newRegulation.applicable_batches.map((batch) => (
                          <label className="choice" key={batch}>
                            <input type="checkbox" checked={batches.includes(batch)} onChange={(event) => setBatches(available(batches, batch, event.target.checked))} />
                            <span>{batch}</span>
                          </label>
                        ))}
                      </fieldset>
                      <fieldset className="field">
                        <legend>Applicable programmes</legend>
                        {newRegulation.applicable_programmes.map((programme) => (
                          <label className="choice" key={programme}>
                            <input type="checkbox" checked={programmes.includes(programme)} onChange={(event) => setProgrammes(available(programmes, programme, event.target.checked))} />
                            <span>{programme}</span>
                          </label>
                        ))}
                      </fieldset>
                    </div>
                  ) : null}
                  <button type="button" className="button button--primary" disabled={busy !== null} onClick={compare}>
                    {busy === "create" ? "Comparing…" : "Compare and save for review"}
                  </button>
                </div>
              )}
            </>
          )}
        </Loaded>
      </Card>
      {demoReview ? (
        <Card title="Comparison result">
          <details className="panel change-review" open>
            <summary>
              <span><strong>{demoReview.previous_document_name}</strong> · {demoReview.previous_version} → <strong>{demoReview.new_document_name}</strong> · {demoReview.new_version}</span>
              <Badge tone="caution">Needs review</Badge>
            </summary>
            <p className="muted">
              {demoReview.changes.length} potential differences ·{" "}
              {demoReview.changes.filter((c) => c.change_type === "modification").length} modified ·{" "}
              {demoReview.changes.filter((c) => c.change_type === "addition").length} added ·{" "}
              {demoReview.changes.filter((c) => c.change_type === "removal").length} removed
              <br />Applies to batches {demoReview.applicable_batches.join(", ")} · programmes {demoReview.applicable_programmes.join(", ")}
            </p>
            <ReviewEvidence review={demoReview} />
            <p className="muted">Demo comparison generated from V1.pdf and V2.pdf; it is not saved and is not shown to students.</p>
          </details>
        </Card>
      ) : null}
      <Card title="Saved comparisons">
        <Loaded resource={reviews}>
          {(saved: ChangeReview[]) => saved.length ? (
            <div className="change-review__list">
              {saved.map((review) => (
                <details className="panel change-review" key={review.id}>
                  <summary>
                    <span><strong>{review.previous_document_name}</strong> · {review.previous_version} → {review.new_version}</span>
                    <Badge tone={review.status === "approved" ? "good" : "caution"}>{review.status === "approved" ? "Approved" : "Needs review"}</Badge>
                  </summary>
                  <p className="muted">
                    Review #{review.id} · {review.changes.length} potential differences · saved {formatDate(review.created_at, true)}
                    <br />Applies to batches {review.applicable_batches.join(", ")} · programmes {review.applicable_programmes.join(", ")}
                  </p>
                  <ReviewEvidence review={review} />
                  <div className="button-row">
                    {review.status === "needs_review" ? (
                      <button type="button" className="button button--primary" disabled={busy !== null} onClick={() => setStatus(review, "approved")}>
                        {busy === review.id ? "Saving…" : "Approve reviewed changes"}
                      </button>
                    ) : (
                      <button type="button" className="button button--ghost" disabled={busy !== null} onClick={() => setStatus(review, "needs_review")}>
                        {busy === review.id ? "Saving…" : "Return to Needs review"}
                      </button>
                    )}
                    <span className="muted">Approval does not publish or approve the underlying regulation PDF.</span>
                  </div>
                </details>
              ))}
            </div>
          ) : <EmptyState title="No comparisons saved yet">Compare two real regulation versions to start a review.</EmptyState>}
        </Loaded>
      </Card>
    </div>
  );
}
