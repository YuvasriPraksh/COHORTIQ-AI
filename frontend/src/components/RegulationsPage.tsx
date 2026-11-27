import { useState, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { ingestRegulation, listCohortRegulations, listRegulations, setVerification } from "../api/cohortiq";
import {
  MAX_UPLOAD_BYTES,
  type IngestionResult,
  type Regulation,
  type UserProfile,
  type VerificationStatus,
} from "../api/types";
import { useSession } from "../auth/session";
import { useResource } from "../hooks/useResource";
import { Notice } from "./Notice";
import { RegulationPages } from "./PageText";
import { Card, ConfirmButton, EmptyState, Loaded, PageHeader, VerificationBadge, formatDate } from "./ui";

function splitList(raw: string): string[] {
  return raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function IngestRegulationForm({ token, onIngested }: { token: string; onIngested: () => void }) {
  const { handleUnauthorized } = useSession();
  const [file, setFile] = useState<File | null>(null);
  const [documentName, setDocumentName] = useState("");
  const [version, setVersion] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [batches, setBatches] = useState("");
  const [programmes, setProgrammes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestionResult | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setResult(null);

    const batchList = splitList(batches);
    const programmeList = splitList(programmes);
    if (!file) {
      setError("Choose a PDF regulation document to upload.");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".pdf") && file.type !== "application/pdf") {
      setError("Only PDF files are accepted.");
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setError("The selected PDF exceeds the 20 MB upload limit.");
      return;
    }
    if (!documentName.trim() || !version.trim() || !/^\d{4}-\d{2}-\d{2}$/.test(effectiveDate.trim())) {
      setError("Enter a document name, version, and effective date in YYYY-MM-DD format.");
      return;
    }
    if (!batchList.length || !programmeList.length) {
      setError("Enter at least one admission batch and one programme (comma-separated).");
      return;
    }

    const form = new FormData();
    form.append("file", file);
    form.append("document_name", documentName.trim());
    form.append("regulation_version", version.trim());
    form.append("effective_date", effectiveDate.trim());
    for (const b of batchList) form.append("applicable_batches", b);
    for (const p of programmeList) form.append("applicable_programmes", p);

    setSubmitting(true);
    try {
      const res = await ingestRegulation(token, form);
      setResult(res);
      setFile(null);
      setDocumentName("");
      setVersion("");
      setEffectiveDate("");
      setBatches("");
      setProgrammes("");
      onIngested();
    } catch (caught) {
      if (caught instanceof ApiError && caught.kind === "unauthorized") {
        handleUnauthorized();
        return;
      }
      setError(caught instanceof ApiError ? caught.message : "Upload failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card title="Ingest regulation PDF (Pending review)">
      <p className="muted">
        Uploaded PDFs are extracted with PyMuPDF and stored as <strong>pending</strong> until an administrator
        explicitly approves them.
      </p>
      {error ? <Notice tone="error" title={error} /> : null}
      {result ? (
        <Notice tone="info" title={result.message}>
          {result.extraction_summary ? (
            <span>
              Extracted {result.extraction_summary.successful_pages ?? 0} of{" "}
              {result.extraction_summary.total_pages ?? 0} pages (status:{" "}
              {result.verification_status ?? "pending"}).
            </span>
          ) : null}
        </Notice>
      ) : null}
      <form onSubmit={onSubmit} className="form" noValidate>
        <label className="field">
          <span>Regulation PDF (max 20 MB)</span>
          <input
            type="file"
            accept=".pdf,application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <div className="field-row">
          <label className="field">
            <span>Document name</span>
            <input
              value={documentName}
              onChange={(e) => setDocumentName(e.target.value)}
              placeholder="e.g. SMVEC R2024"
              maxLength={200}
            />
          </label>
          <label className="field">
            <span>Version</span>
            <input
              value={version}
              onChange={(e) => setVersion(e.target.value)}
              placeholder="e.g. 2024"
              maxLength={50}
            />
          </label>
          <label className="field">
            <span>Effective date</span>
            <input
              type="date"
              value={effectiveDate}
              onChange={(e) => setEffectiveDate(e.target.value)}
              placeholder="YYYY-MM-DD"
            />
          </label>
        </div>
        <div className="field-row">
          <label className="field">
            <span>Applicable batches (comma-separated)</span>
            <input
              value={batches}
              onChange={(e) => setBatches(e.target.value)}
              placeholder="e.g. 2024, 2025"
            />
          </label>
          <label className="field">
            <span>Applicable programmes (comma-separated)</span>
            <input
              value={programmes}
              onChange={(e) => setProgrammes(e.target.value)}
              placeholder="e.g. B-tech - CSE"
            />
          </label>
        </div>
        <div>
          <button type="submit" className="button button--primary" disabled={submitting}>
            {submitting ? <span className="spinner" aria-hidden="true" /> : null}
            {submitting ? "Extracting & ingesting…" : "Upload & extract PDF"}
          </button>
        </div>
      </form>
    </Card>
  );
}

export function RegulationsPage({ token, user }: { token: string; user: UserProfile }) {
  const { handleUnauthorized } = useSession();
  const isAdmin = user.role === "administrator";
  const hasCohort = Boolean(user.admission_batch && user.programme);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const resourceKey = isAdmin
    ? "regulations:all"
    : hasCohort
      ? `regulations:cohort:${user.admission_batch}:${user.programme}`
      : "regulations:none";

  const regulations = useResource<Regulation[]>(resourceKey, async (signal) => {
    if (isAdmin) return listRegulations(token, signal);
    if (!user.admission_batch || !user.programme) return [];
    return listCohortRegulations(
      token,
      { admission_batch: user.admission_batch, programme: user.programme },
      signal,
    );
  });

  async function updateStatus(id: number, status: VerificationStatus) {
    setBusyId(id);
    setActionError(null);
    try {
      await setVerification(token, id, status);
      regulations.reload();
    } catch (caught) {
      if (caught instanceof ApiError && caught.kind === "unauthorized") {
        handleUnauthorized();
        return;
      }
      setActionError(caught instanceof ApiError ? caught.message : "Could not update verification status.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="stack">
      <PageHeader
        title={isAdmin ? "Regulations & document ingestion" : "Your cohort regulations"}
        subtitle={
          isAdmin
            ? "Upload regulation PDFs, review extracted pages, and manage approval status."
            : hasCohort
              ? `Approved regulations applicable to Batch ${user.admission_batch} · ${user.programme}.`
              : "Your account does not have an admission batch and programme assigned yet."
        }
      />

      {!isAdmin && !hasCohort ? (
        <Notice tone="warning" title="Your cohort isn't set">
          Ask an administrator to assign your admission batch and programme so applicable regulations can be shown.
        </Notice>
      ) : null}

      {isAdmin ? <IngestRegulationForm token={token} onIngested={regulations.reload} /> : null}

      {actionError ? <Notice tone="error" title={actionError} /> : null}

      <Card
        title={isAdmin ? "Stored regulations" : "Applicable approved regulations"}
        actions={
          <button type="button" className="button button--ghost button--compact" onClick={regulations.reload}>
            Refresh
          </button>
        }
      >
        <Loaded resource={regulations}>
          {(list) =>
            list.length === 0 ? (
              <EmptyState title="No applicable regulations found">
                {isAdmin
                  ? "Upload a regulation PDF above to get started."
                  : "No approved regulation currently covers your cohort."}
              </EmptyState>
            ) : (
              <div className="reg-list">
                {list.map((reg) => {
                  const isOpen = selectedId === reg.id;
                  return (
                    <article key={reg.id} className="reg-item">
                      <div className="reg-item__head">
                        <div>
                          <h3 className="reg-item__title">
                            {reg.document_name} <span className="citation__tag">v{reg.regulation_version}</span>
                          </h3>
                          <p className="reg-item__meta">
                            Effective {formatDate(reg.effective_date)} · {reg.total_pages ?? "?"} pages
                          </p>
                          <p className="reg-item__meta">
                            Batches: {reg.applicable_batches.join(", ") || "None"} · Programmes:{" "}
                            {reg.applicable_programmes.join(", ") || "None"}
                          </p>
                        </div>
                        <div className="reg-item__actions">
                          <VerificationBadge status={reg.verification_status} />
                          <button
                            type="button"
                            className="button button--ghost button--compact"
                            onClick={() => setSelectedId(isOpen ? null : reg.id)}
                          >
                            {isOpen ? "Hide pages" : "Read pages"}
                          </button>
                        </div>
                      </div>

                      {isAdmin ? (
                        <div className="reg-item__admin">
                          {reg.verification_status !== "approved" ? (
                            <ConfirmButton
                              label="Approve"
                              confirmLabel="Confirm approve"
                              variant="primary"
                              disabled={busyId === reg.id}
                              onConfirm={() => void updateStatus(reg.id, "approved")}
                            />
                          ) : null}
                          {reg.verification_status !== "rejected" ? (
                            <ConfirmButton
                              label="Reject"
                              confirmLabel="Confirm reject"
                              disabled={busyId === reg.id}
                              onConfirm={() => void updateStatus(reg.id, "rejected")}
                            />
                          ) : null}
                          {reg.verification_status !== "pending" ? (
                            <ConfirmButton
                              label="Set pending"
                              confirmLabel="Confirm pending"
                              disabled={busyId === reg.id}
                              onConfirm={() => void updateStatus(reg.id, "pending")}
                            />
                          ) : null}
                        </div>
                      ) : null}

                      {isOpen ? (
                        <div className="reg-item__pages">
                          <RegulationPages token={token} regulationId={reg.id} />
                        </div>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            )
          }
        </Loaded>
      </Card>
    </div>
  );
}
