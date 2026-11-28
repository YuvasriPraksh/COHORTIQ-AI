import { useMemo, useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import { listRegulations, setVerification } from "../api/cohortiq";
import type { Regulation, VerificationStatus } from "../api/types";
import { useSession } from "../auth/session";
import { useResource } from "../hooks/useResource";
import { navigate } from "../nav/router";
import { Icon } from "./icons";
import { Notice } from "./Notice";
import { RegulationPages } from "./PageText";
import {
  ConfirmButton,
  Drawer,
  EmptyState,
  Loaded,
  PageHeader,
  ProcessingBadge,
  StatCard,
  VerificationBadge,
  formatDate,
  isExtracted,
} from "./ui";

const LEGACY_FILENAME = "Filename unavailable for legacy upload";

function norm(value: string | null | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

/** Change Radar compares a new version against an approved version with the same document name. */
function comparisonPartner(reg: Regulation, all: Regulation[]): Regulation | undefined {
  return all.find(
    (other) =>
      other.id !== reg.id &&
      norm(other.document_name) === norm(reg.document_name) &&
      norm(other.regulation_version) !== norm(reg.regulation_version) &&
      norm(other.verification_status) === "approved",
  );
}

function DetailsPanel({ reg, onClose, onReadPages }: { reg: Regulation; onClose: () => void; onReadPages: () => void }) {
  const rows: [string, ReactNode][] = [
    ["Document name", reg.document_name],
    ["Original filename", reg.source_filename || <span className="muted">{LEGACY_FILENAME}</span>],
    ["Version", reg.regulation_version],
    ["Regulation ID", `#${reg.id}`],
    ["Uploaded", formatDate(reg.upload_date)],
    ["Effective date", formatDate(reg.effective_date)],
    ["Pages extracted", reg.total_pages ?? "Not recorded"],
    ["Admission batches", reg.applicable_batches.join(", ") || "None"],
    ["Programmes", reg.applicable_programmes.join(", ") || "None"],
    ["Processing status", <ProcessingBadge status={reg.processing_status} />],
    ["Approval status", <VerificationBadge status={reg.verification_status} />],
  ];
  return (
    <Drawer title={reg.document_name} subtitle={`Version ${reg.regulation_version}`} onClose={onClose}>
      <dl className="detail-list">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <div className="availability">
        <div className={`availability__item${isExtracted(reg.processing_status) ? " is-yes" : " is-no"}`}>
          <Icon name={isExtracted(reg.processing_status) ? "checkCircle" : "alert"} size={18} />
          <div>
            <strong>Extracted text</strong>
            <span>{isExtracted(reg.processing_status) ? `Available for ${reg.total_pages ?? "all"} pages — used for retrieval and citations.` : "Not available for this document."}</span>
          </div>
        </div>
        <div className="availability__item is-no">
          <Icon name="info" size={18} />
          <div>
            <strong>Original PDF file</strong>
            <span>Not stored. CohortIQ keeps the extracted page text only, so the PDF cannot be downloaded here.</span>
          </div>
        </div>
      </div>
      <button type="button" className="button button--primary" onClick={onReadPages}>
        <Icon name="pages" size={16} /> Read extracted pages
      </button>
    </Drawer>
  );
}

export function StoredRegulationsPage({ token }: { token: string }) {
  const { handleUnauthorized } = useSession();
  const regulations = useResource<Regulation[]>("regulations:all", (signal) => listRegulations(token, signal));
  const [search, setSearch] = useState("");
  const [version, setVersion] = useState("");
  const [batch, setBatch] = useState("");
  const [programme, setProgramme] = useState("");
  const [approval, setApproval] = useState("");
  const [processing, setProcessing] = useState("");
  const [sort, setSort] = useState<"newest" | "oldest">("newest");
  const [detailsId, setDetailsId] = useState<number | null>(null);
  const [pagesId, setPagesId] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  const all = regulations.status === "ready" ? regulations.data : [];

  const options = useMemo(
    () => ({
      versions: unique(all.map((r) => r.regulation_version)),
      batches: unique(all.flatMap((r) => r.applicable_batches)),
      programmes: unique(all.flatMap((r) => r.applicable_programmes)),
    }),
    [all],
  );

  const filtered = useMemo(() => {
    const term = norm(search);
    const list = all.filter((r) => {
      if (term && !norm(r.document_name).includes(term) && !norm(r.source_filename).includes(term)) return false;
      if (version && r.regulation_version !== version) return false;
      if (batch && !r.applicable_batches.includes(batch)) return false;
      if (programme && !r.applicable_programmes.includes(programme)) return false;
      if (approval && norm(r.verification_status || "pending") !== approval) return false;
      if (processing === "extracted" && !isExtracted(r.processing_status)) return false;
      if (processing === "issues" && isExtracted(r.processing_status)) return false;
      return true;
    });
    return list.sort((a, b) => {
      const byDate = (a.upload_date ?? "").localeCompare(b.upload_date ?? "") || a.id - b.id;
      return sort === "newest" ? -byDate : byDate;
    });
  }, [all, search, version, batch, programme, approval, processing, sort]);

  const filtersActive = Boolean(search || version || batch || programme || approval || processing);

  function resetFilters() {
    setSearch("");
    setVersion("");
    setBatch("");
    setProgramme("");
    setApproval("");
    setProcessing("");
  }

  async function updateStatus(reg: Regulation, status: VerificationStatus) {
    setBusyId(reg.id);
    setActionError(null);
    setActionNotice(null);
    try {
      await setVerification(token, reg.id, status);
      setActionNotice(
        status === "approved"
          ? `${reg.document_name} ${reg.regulation_version} approved. It is now searchable for its batches and programmes.`
          : status === "rejected"
            ? `${reg.document_name} ${reg.regulation_version} rejected. It will not be used for answers.`
            : `${reg.document_name} ${reg.regulation_version} returned to pending. It will not be used for answers until approved.`,
      );
      regulations.reload();
    } catch (caught) {
      if (caught instanceof ApiError && caught.kind === "unauthorized") {
        handleUnauthorized();
        return;
      }
      setActionError(caught instanceof ApiError ? caught.message : "Could not update the approval status.");
    } finally {
      setBusyId(null);
    }
  }

  const details = all.find((r) => r.id === detailsId) ?? null;
  const pagesReg = all.find((r) => r.id === pagesId) ?? null;
  const counts = {
    total: all.length,
    approved: all.filter((r) => norm(r.verification_status) === "approved").length,
    pending: all.filter((r) => !r.verification_status || norm(r.verification_status) === "pending").length,
    rejected: all.filter((r) => norm(r.verification_status) === "rejected").length,
    issues: all.filter((r) => !isExtracted(r.processing_status)).length,
  };

  return (
    <div className="page-stack">
      <PageHeader
        icon="files"
        title="Stored Regulations"
        subtitle="Every regulation document in the database, with its extraction and approval status. Only approved documents are used for answers."
        actions={
          <>
            <button type="button" className="button button--ghost" onClick={regulations.reload}>
              <Icon name="refresh" size={16} /> Refresh
            </button>
            <button type="button" className="button button--primary" onClick={() => navigate("/admin/upload")}>
              <Icon name="upload" size={16} /> Upload
            </button>
          </>
        }
      />

      <div className="stat-grid">
        <StatCard label="Total documents" value={regulations.status === "ready" ? counts.total : "—"} icon="files" tone="blue" />
        <StatCard label="Approved" value={regulations.status === "ready" ? counts.approved : "—"} icon="checkCircle" tone="emerald" hint="Searchable by their cohorts" />
        <StatCard label="Pending approval" value={regulations.status === "ready" ? counts.pending : "—"} icon="clock" tone="amber" hint={counts.rejected ? `${counts.rejected} rejected` : undefined} />
        <StatCard label="Extraction issues" value={regulations.status === "ready" ? counts.issues : "—"} icon="alert" tone="rose" hint="Not marked as extracted" />
      </div>

      {actionError ? <Notice tone="error" title={actionError} /> : null}
      {actionNotice ? <Notice tone="info" title={actionNotice} /> : null}

      <section className="panel table-panel">
        <div className="toolbar">
          <label className="toolbar__search">
            <Icon name="search" size={16} />
            <span className="visually-hidden">Search by document name or filename</span>
            <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search document name or filename" />
          </label>
          <label className="select">
            <span className="visually-hidden">Filter by version</span>
            <select value={version} onChange={(e) => setVersion(e.target.value)}>
              <option value="">All versions</option>
              {options.versions.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </label>
          <label className="select">
            <span className="visually-hidden">Filter by admission batch</span>
            <select value={batch} onChange={(e) => setBatch(e.target.value)}>
              <option value="">All batches</option>
              {options.batches.map((v) => <option key={v} value={v}>Batch {v}</option>)}
            </select>
          </label>
          <label className="select">
            <span className="visually-hidden">Filter by programme</span>
            <select value={programme} onChange={(e) => setProgramme(e.target.value)}>
              <option value="">All programmes</option>
              {options.programmes.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </label>
          <label className="select">
            <span className="visually-hidden">Filter by approval status</span>
            <select value={approval} onChange={(e) => setApproval(e.target.value)}>
              <option value="">Any approval</option>
              <option value="approved">Approved</option>
              <option value="pending">Pending</option>
              <option value="rejected">Rejected</option>
            </select>
          </label>
          <label className="select">
            <span className="visually-hidden">Filter by processing status</span>
            <select value={processing} onChange={(e) => setProcessing(e.target.value)}>
              <option value="">Any processing</option>
              <option value="extracted">Text extracted</option>
              <option value="issues">Extraction issues</option>
            </select>
          </label>
          <label className="select">
            <span className="visually-hidden">Sort by upload date</span>
            <select value={sort} onChange={(e) => setSort(e.target.value as "newest" | "oldest")}>
              <option value="newest">Newest uploads first</option>
              <option value="oldest">Oldest uploads first</option>
            </select>
          </label>
          {filtersActive ? (
            <button type="button" className="button button--ghost button--compact" onClick={resetFilters}>Reset</button>
          ) : null}
        </div>

        <Loaded resource={regulations}>
          {(list) =>
            list.length === 0 ? (
              <EmptyState title="No regulations stored yet" action={<button type="button" className="button button--primary" onClick={() => navigate("/admin/upload")}>Upload the first PDF</button>}>
                Upload a regulation PDF to start building the knowledge base.
              </EmptyState>
            ) : filtered.length === 0 ? (
              <EmptyState title="No documents match these filters" action={<button type="button" className="button button--ghost" onClick={resetFilters}>Reset filters</button>} />
            ) : (
              <>
                <p className="table-count">Showing {filtered.length} of {list.length} documents</p>
                <div className="table-wrap">
                  <table className="data-table data-table--docs">
                    <thead>
                      <tr>
                        <th scope="col">Document</th>
                        <th scope="col">Version</th>
                        <th scope="col">Dates</th>
                        <th scope="col" className="num">Pages</th>
                        <th scope="col">Applies to</th>
                        <th scope="col">Status</th>
                        <th scope="col">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((reg) => {
                        const partner = comparisonPartner(reg, list);
                        const status = norm(reg.verification_status) || "pending";
                        return (
                          <tr key={reg.id}>
                            <td data-label="Document">
                              <div className="doc-cell">
                                <span className="doc-cell__icon"><Icon name="file" size={18} /></span>
                                <div>
                                  <strong>{reg.document_name}</strong>
                                  <span className={reg.source_filename ? "doc-cell__file" : "doc-cell__file is-legacy"}>
                                    {reg.source_filename || LEGACY_FILENAME}
                                  </span>
                                </div>
                              </div>
                            </td>
                            <td data-label="Version"><span className="tag">{reg.regulation_version}</span></td>
                            <td data-label="Dates">
                              <div className="dates-cell">
                                <span><small>Uploaded</small>{formatDate(reg.upload_date)}</span>
                                <span><small>Effective</small>{formatDate(reg.effective_date)}</span>
                              </div>
                            </td>
                            <td data-label="Pages" className="num">{reg.total_pages ?? "—"}</td>
                            <td data-label="Applies to">
                              <div className="applies-cell">
                                <span><small>Batches</small>{reg.applicable_batches.join(", ") || "—"}</span>
                                <span><small>Programmes</small>{reg.applicable_programmes.join(", ") || "—"}</span>
                              </div>
                            </td>
                            <td data-label="Status">
                              <div className="status-cell">
                                <VerificationBadge status={reg.verification_status} />
                                <ProcessingBadge status={reg.processing_status} />
                              </div>
                            </td>
                            <td data-label="Actions">
                              <div className="row-actions">
                                <button type="button" className="button button--ghost button--compact" onClick={() => setDetailsId(reg.id)}>
                                  <Icon name="eye" size={15} /> Details
                                </button>
                                <button type="button" className="button button--ghost button--compact" onClick={() => setPagesId(reg.id)}>
                                  <Icon name="pages" size={15} /> Pages
                                </button>
                                {status !== "approved" ? (
                                  <ConfirmButton label="Approve" confirmLabel="Confirm approve" variant="primary" disabled={busyId === reg.id} onConfirm={() => void updateStatus(reg, "approved")} />
                                ) : null}
                                {status !== "rejected" ? (
                                  <ConfirmButton label="Reject" confirmLabel="Confirm reject" disabled={busyId === reg.id} onConfirm={() => void updateStatus(reg, "rejected")} />
                                ) : null}
                                {status !== "pending" ? (
                                  <ConfirmButton label="Set pending" confirmLabel="Confirm pending" disabled={busyId === reg.id} onConfirm={() => void updateStatus(reg, "pending")} />
                                ) : null}
                                {partner ? (
                                  <button type="button" className="button button--ghost button--compact" title={`Compare with ${partner.regulation_version}`} onClick={() => navigate(`/admin/change-radar?new=${reg.id}`)}>
                                    <Icon name="compare" size={15} /> Compare
                                  </button>
                                ) : null}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            )
          }
        </Loaded>
      </section>

      {details ? (
        <DetailsPanel
          reg={details}
          onClose={() => setDetailsId(null)}
          onReadPages={() => {
            setDetailsId(null);
            setPagesId(details.id);
          }}
        />
      ) : null}
      {pagesReg ? (
        <Drawer wide title={`${pagesReg.document_name} · ${pagesReg.regulation_version}`} subtitle="Extracted page text" onClose={() => setPagesId(null)}>
          <RegulationPages token={token} regulationId={pagesReg.id} />
        </Drawer>
      ) : null}
    </div>
  );
}
