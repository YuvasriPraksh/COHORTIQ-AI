import { useState } from "react";

import { listCohortRegulations } from "../api/cohortiq";
import type { Regulation, UserProfile } from "../api/types";
import { useResource } from "../hooks/useResource";
import { Icon } from "./icons";
import { Notice } from "./Notice";
import { RegulationPages } from "./PageText";
import { Drawer, EmptyState, Loaded, PageHeader, VerificationBadge, formatDate } from "./ui";

/** Approved regulations for a student's or staff member's own cohort (the API enforces the scope). */
export function RegulationsPage({ token, user }: { token: string; user: UserProfile }) {
  const hasCohort = Boolean(user.admission_batch && user.programme);
  const [openId, setOpenId] = useState<number | null>(null);

  const regulations = useResource<Regulation[]>(
    hasCohort ? `regulations:cohort:${user.admission_batch}:${user.programme}` : "regulations:none",
    async (signal) => {
      if (!user.admission_batch || !user.programme) return [];
      return listCohortRegulations(token, { admission_batch: user.admission_batch, programme: user.programme }, signal);
    },
  );
  const open = regulations.status === "ready" ? regulations.data.find((reg) => reg.id === openId) : undefined;

  return (
    <div className="page-stack">
      <PageHeader
        icon="book"
        title={user.role === "staff" ? "Assigned cohort regulations" : "Your cohort regulations"}
        subtitle={
          hasCohort
            ? `Approved regulations applicable to Batch ${user.admission_batch} · ${user.programme}.`
            : "Your account does not have an admission batch and programme assigned yet."
        }
        actions={
          <button type="button" className="button button--ghost" onClick={regulations.reload}>
            <Icon name="refresh" size={16} /> Refresh
          </button>
        }
      />

      {!hasCohort ? (
        <Notice tone="warning" title="Your cohort isn't set">
          Ask an administrator to assign your admission batch and programme so applicable regulations can be shown.
        </Notice>
      ) : null}

      <Loaded resource={regulations}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState title="No applicable regulations found">No approved regulation currently covers your cohort.</EmptyState>
          ) : (
            <div className="doc-grid">
              {list.map((reg) => (
                <article key={reg.id} className="doc-card">
                  <div className="doc-card__top">
                    <span className="doc-card__icon"><Icon name="book" size={20} /></span>
                    <VerificationBadge status={reg.verification_status} />
                  </div>
                  <h2 className="doc-card__title">
                    {reg.document_name} <span className="tag">v{reg.regulation_version}</span>
                  </h2>
                  <dl className="doc-card__meta">
                    <div><dt>Effective</dt><dd>{formatDate(reg.effective_date)}</dd></div>
                    <div><dt>Pages</dt><dd>{reg.total_pages ?? "?"}</dd></div>
                    <div><dt>Batches</dt><dd>{reg.applicable_batches.join(", ") || "—"}</dd></div>
                    <div><dt>Programmes</dt><dd>{reg.applicable_programmes.join(", ") || "—"}</dd></div>
                  </dl>
                  <button type="button" className="button button--ghost button--wide" onClick={() => setOpenId(reg.id)}>
                    <Icon name="pages" size={16} /> Read pages
                  </button>
                </article>
              ))}
            </div>
          )
        }
      </Loaded>

      {open ? (
        <Drawer wide title={`${open.document_name} · v${open.regulation_version}`} subtitle="Extracted page text" onClose={() => setOpenId(null)}>
          <RegulationPages token={token} regulationId={open.id} />
        </Drawer>
      ) : null}
    </div>
  );
}
