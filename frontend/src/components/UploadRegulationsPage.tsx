import { useRef, useState, type DragEvent } from "react";

import { ApiError } from "../api/client";
import { ingestRegulation } from "../api/cohortiq";
import { MAX_UPLOAD_BYTES, type IngestionResult } from "../api/types";
import { useSession } from "../auth/session";
import { navigate } from "../nav/router";
import { Icon } from "./icons";
import { Notice } from "./Notice";
import { Badge, PageHeader } from "./ui";

type ItemStatus = "ready" | "uploading" | "done" | "failed";

interface QueueItem {
  id: number;
  file: File;
  documentName: string;
  version: string;
  effectiveDate: string;
  batches: string;
  programmes: string;
  status: ItemStatus;
  result?: IngestionResult;
  error?: string;
}

function splitList(raw: string): string[] {
  return raw.split(",").map((item) => item.trim()).filter(Boolean);
}

function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function nameFromFile(file: File): string {
  return file.name.replace(/\.pdf$/i, "").replace(/[_]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 200);
}

function validate(item: QueueItem): string | null {
  if (!item.documentName.trim() || !item.version.trim()) return "Enter a document name and version.";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(item.effectiveDate.trim())) return "Choose an effective date.";
  if (!splitList(item.batches).length || !splitList(item.programmes).length) {
    return "Enter at least one admission batch and one programme (comma-separated).";
  }
  return null;
}

let nextId = 1;

export function UploadRegulationsPage({ token }: { token: string }) {
  const { handleUnauthorized } = useSession();
  const [items, setItems] = useState<QueueItem[]>([]);
  const [rejected, setRejected] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const [running, setRunning] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  function update(id: number, changes: Partial<QueueItem>) {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, ...changes } : item)));
  }

  function addFiles(list: FileList | File[]) {
    const accepted: QueueItem[] = [];
    const refused: string[] = [];
    const template = [...items].reverse().find((item) => item.status !== "done") ?? items[items.length - 1];
    {
      for (const file of Array.from(list)) {
        if (!file.name.toLowerCase().endsWith(".pdf") && file.type !== "application/pdf") {
          refused.push(`${file.name}: only PDF files are accepted.`);
          continue;
        }
        if (file.size > MAX_UPLOAD_BYTES) {
          refused.push(`${file.name}: larger than the 20 MB upload limit (${formatSize(file.size)}).`);
          continue;
        }
        accepted.push({
          id: nextId++,
          file,
          documentName: nameFromFile(file),
          version: "",
          effectiveDate: template?.effectiveDate ?? "",
          batches: template?.batches ?? "",
          programmes: template?.programmes ?? "",
          status: "ready",
        });
      }
    }
    setItems((current) => [...current, ...accepted]);
    setRejected(refused);
  }

  async function upload(item: QueueItem): Promise<void> {
    const problem = validate(item);
    if (problem) {
      update(item.id, { status: "failed", error: problem });
      return;
    }
    const form = new FormData();
    form.append("file", item.file);
    form.append("document_name", item.documentName.trim());
    form.append("regulation_version", item.version.trim());
    form.append("effective_date", item.effectiveDate.trim());
    for (const b of splitList(item.batches)) form.append("applicable_batches", b);
    for (const p of splitList(item.programmes)) form.append("applicable_programmes", p);

    update(item.id, { status: "uploading", error: undefined, result: undefined });
    try {
      const result = await ingestRegulation(token, form);
      update(item.id, { status: "done", result });
    } catch (caught) {
      if (caught instanceof ApiError && caught.kind === "unauthorized") {
        handleUnauthorized();
        return;
      }
      update(item.id, { status: "failed", error: caught instanceof ApiError ? caught.message : "Upload failed. Please try again." });
    }
  }

  async function uploadAll() {
    setRunning(true);
    // Sequential: each PDF is extracted on the server before the next one is sent.
    for (const item of items) {
      if (item.status === "ready" || item.status === "failed") {
        // eslint-disable-next-line no-await-in-loop
        await upload(item);
      }
    }
    setRunning(false);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) addFiles(event.dataTransfer.files);
  }

  const pending = items.filter((item) => item.status === "ready" || item.status === "failed").length;
  const done = items.filter((item) => item.status === "done").length;

  return (
    <div className="page-stack">
      <PageHeader
        icon="upload"
        title="Upload Regulations"
        subtitle="Add regulation PDFs with their applicability. Each document is extracted page by page and stored as pending until you approve it in Stored Regulations."
      />

      <div
        className={`dropzone${dragging ? " is-dragging" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <span className="dropzone__icon"><Icon name="upload" size={28} /></span>
        <h2 className="dropzone__title">Drag and drop regulation PDFs here</h2>
        <p className="dropzone__text">PDF only · up to 20 MB and 500 pages per file · add as many documents as you need</p>
        <button type="button" className="button button--primary" onClick={() => inputRef.current?.click()}>
          <Icon name="files" size={16} /> Browse files
        </button>
        <input
          ref={inputRef}
          className="visually-hidden"
          type="file"
          accept=".pdf,application/pdf"
          multiple
          aria-label="Choose regulation PDF files"
          onChange={(event) => {
            if (event.target.files?.length) addFiles(event.target.files);
            event.target.value = "";
          }}
        />
      </div>

      {rejected.length ? (
        <Notice tone="error" title={`${rejected.length} file${rejected.length > 1 ? "s were" : " was"} not added`}>
          <ul className="plain-list">{rejected.map((line) => <li key={line}>{line}</li>)}</ul>
        </Notice>
      ) : null}

      {items.length ? (
        <section className="upload-queue" aria-label="Upload queue">
          <div className="upload-queue__head">
            <div>
              <h2 className="section-title">Upload queue</h2>
              <p className="muted">{items.length} file{items.length > 1 ? "s" : ""} · {done} stored · {pending} waiting</p>
            </div>
            <div className="button-row">
              {done ? (
                <button type="button" className="button button--ghost button--compact" onClick={() => setItems((current) => current.filter((item) => item.status !== "done"))}>
                  Clear stored
                </button>
              ) : null}
              <button type="button" className="button button--primary" disabled={!pending || running} onClick={() => void uploadAll()}>
                {running ? <span className="spinner" aria-hidden="true" /> : <Icon name="upload" size={16} />}
                {running ? "Uploading…" : `Upload ${pending || ""} document${pending === 1 ? "" : "s"}`.replace("  ", " ")}
              </button>
            </div>
          </div>

          {items.map((item) => {
            const locked = item.status === "uploading" || item.status === "done";
            return (
              <article key={item.id} className={`upload-item upload-item--${item.status}`}>
                <header className="upload-item__head">
                  <span className="upload-item__file"><Icon name="file" size={18} /></span>
                  <div className="upload-item__name">
                    <strong>{item.file.name}</strong>
                    <span>{formatSize(item.file.size)}</span>
                  </div>
                  {item.status === "ready" ? <Badge tone="neutral">Ready to upload</Badge> : null}
                  {item.status === "uploading" ? <Badge tone="info">Uploading &amp; extracting</Badge> : null}
                  {item.status === "done" ? <Badge tone="good">Stored · pending approval</Badge> : null}
                  {item.status === "failed" ? <Badge tone="bad">Failed</Badge> : null}
                  {!locked ? (
                    <button type="button" className="icon-button" aria-label={`Remove ${item.file.name}`} onClick={() => setItems((current) => current.filter((entry) => entry.id !== item.id))}>
                      <Icon name="x" size={16} />
                    </button>
                  ) : null}
                </header>

                {item.status === "uploading" ? (
                  <div className="progress" role="progressbar" aria-label={`Uploading ${item.file.name}`} aria-valuetext="Uploading and extracting text">
                    <span />
                  </div>
                ) : null}

                {item.status === "done" && item.result ? (
                  <div className="upload-item__result">
                    <Icon name="checkCircle" size={18} />
                    <div>
                      <strong>{item.result.message}</strong>
                      {item.result.extraction_summary ? (
                        <span>
                          Extracted {item.result.extraction_summary.successful_pages ?? 0} of {item.result.extraction_summary.total_pages ?? 0} pages
                          {item.result.extraction_summary.pages_needing_attention ? ` · ${item.result.extraction_summary.pages_needing_attention} need attention` : ""}
                          {item.result.regulation_id != null ? ` · Regulation #${item.result.regulation_id}` : ""}
                        </span>
                      ) : null}
                    </div>
                    <button type="button" className="button button--ghost button--compact" onClick={() => navigate("/admin/regulations")}>
                      Review in Stored Regulations
                    </button>
                  </div>
                ) : null}

                {item.status === "failed" && item.error ? <Notice tone="error" title={item.error} /> : null}

                {item.status !== "done" ? (
                  <div className="upload-item__fields">
                    <label className="field">
                      <span>Document name</span>
                      <input value={item.documentName} disabled={locked} maxLength={200} onChange={(e) => update(item.id, { documentName: e.target.value })} placeholder="e.g. SMVEC B.Tech Regulations" />
                    </label>
                    <label className="field">
                      <span>Version</span>
                      <input value={item.version} disabled={locked} maxLength={50} onChange={(e) => update(item.id, { version: e.target.value })} placeholder="e.g. R2024" />
                    </label>
                    <label className="field">
                      <span>Effective date</span>
                      <input type="date" value={item.effectiveDate} disabled={locked} onChange={(e) => update(item.id, { effectiveDate: e.target.value })} />
                    </label>
                    <label className="field">
                      <span>Admission batches</span>
                      <input value={item.batches} disabled={locked} onChange={(e) => update(item.id, { batches: e.target.value })} placeholder="e.g. 2024, 2025" />
                    </label>
                    <label className="field field--wide">
                      <span>Programmes</span>
                      <input value={item.programmes} disabled={locked} onChange={(e) => update(item.id, { programmes: e.target.value })} placeholder="e.g. B-tech - CSE" />
                    </label>
                    <div className="upload-item__actions">
                      <button type="button" className="button button--ghost button--compact" disabled={locked || running} onClick={() => void upload(item)}>
                        {item.status === "failed" ? "Retry this file" : "Upload this file"}
                      </button>
                    </div>
                  </div>
                ) : null}
              </article>
            );
          })}
        </section>
      ) : (
        <div className="upload-tips">
          <div><Icon name="layers" size={18} /><span><strong>Versions</strong> — to compare in Change Radar, upload a new version with exactly the same document name.</span></div>
          <div><Icon name="target" size={18} /><span><strong>Applicability</strong> — batches and programmes must match student accounts exactly.</span></div>
          <div><Icon name="shield" size={18} /><span><strong>Approval</strong> — nothing is searchable until you approve it.</span></div>
        </div>
      )}
    </div>
  );
}
