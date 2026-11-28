import { useState } from "react";

import {
  listApprovedUpdates,
  listAuditEvents,
  listChangeReviews,
  listCohortRegulations,
  listRegulations,
  listUsers,
} from "../api/cohortiq";
import type { Regulation, UserProfile } from "../api/types";
import { useResource } from "../hooks/useResource";
import { navigate } from "../nav/router";
import { Icon, type IconName } from "./icons";
import { Notice } from "./Notice";
import { EmptyState, Loaded, PageHeader, ProcessingBadge, StatCard, VerificationBadge, formatDate, isExtracted } from "./ui";

function value<T>(resource: { status: string; data: T | null }, pick: (data: T) => number | string) {
  if (resource.status === "ready" && resource.data !== null) return pick(resource.data);
  return resource.status === "error" ? "!" : "—";
}

function QuickAction({ icon, title, text, path, tone }: { icon: IconName; title: string; text: string; path: string; tone: string }) {
  return (
    <button type="button" className={`quick-action tone-${tone}`} onClick={() => navigate(path)}>
      <span className="quick-action__icon"><Icon name={icon} size={20} /></span>
      <span className="quick-action__text">
        <strong>{title}</strong>
        <span>{text}</span>
      </span>
      <Icon name="arrowRight" size={16} className="quick-action__arrow" />
    </button>
  );
}

function greeting(): string {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

function AdminDashboard({ token, user }: { token: string; user: UserProfile }) {
  const [since] = useState(() => new Date(Date.now() - 24 * 3600 * 1000).toISOString());
  const regs = useResource<Regulation[]>("regulations:all", (signal) => listRegulations(token, signal));
  const reviews = useResource("dashboard:reviews", (signal) => listChangeReviews(token, signal));
  const users = useResource("dashboard:users", (signal) => listUsers(token, { limit: 1 }, signal));
  const activity = useResource("dashboard:activity", (signal) => listAuditEvents(token, { occurred_after: since, limit: 1 }, signal));

  const recent = regs.status === "ready" ? [...regs.data].sort((a, b) => b.id - a.id).slice(0, 5) : [];

  return (
    <div className="page-stack">
      <PageHeader icon="grid" title={`${greeting()}${user.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}`} subtitle="An overview of the regulation knowledge base and recent activity." />
      <div className="stat-grid stat-grid--5">
        <StatCard label="Stored documents" value={value(regs, (d) => d.length)} icon="files" tone="blue" />
        <StatCard label="Approved" value={value(regs, (d) => d.filter((r) => r.verification_status === "approved").length)} icon="checkCircle" tone="emerald" />
        <StatCard label="Awaiting approval" value={value(regs, (d) => d.filter((r) => !r.verification_status || r.verification_status === "pending").length)} icon="clock" tone="amber" />
        <StatCard label="Reviews needing attention" value={value(reviews, (d) => d.filter((r) => r.status === "needs_review").length)} icon="radar" tone="violet" />
        <StatCard label="Events · 24h" value={value(activity, (d) => d.total)} icon="activity" tone="teal" hint={users.status === "ready" ? `${users.data.total} accounts` : undefined} />
      </div>

      <div className="dash-grid">
        <section className="panel dash-panel">
          <div className="dash-panel__head">
            <h2 className="section-title">Recent uploads</h2>
            <button type="button" className="button button--ghost button--compact" onClick={() => navigate("/admin/regulations")}>View all</button>
          </div>
          <Loaded resource={regs}>
            {() =>
              recent.length ? (
                <ul className="recent-list">
                  {recent.map((reg) => (
                    <li key={reg.id}>
                      <span className="recent-list__icon"><Icon name="file" size={16} /></span>
                      <div className="recent-list__main">
                        <strong>{reg.document_name} <span className="tag">{reg.regulation_version}</span></strong>
                        <span>{reg.source_filename || "Filename unavailable for legacy upload"} · {formatDate(reg.upload_date)}</span>
                      </div>
                      <div className="recent-list__badges">
                        {!isExtracted(reg.processing_status) ? <ProcessingBadge status={reg.processing_status} /> : null}
                        <VerificationBadge status={reg.verification_status} />
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState title="No regulations yet" action={<button type="button" className="button button--primary" onClick={() => navigate("/admin/upload")}>Upload a PDF</button>} />
              )
            }
          </Loaded>
        </section>
        <section className="dash-actions" aria-label="Quick actions">
          <h2 className="section-title">Quick actions</h2>
          <QuickAction icon="upload" tone="emerald" title="Upload regulations" text="Add one or more PDFs" path="/admin/upload" />
          <QuickAction icon="files" tone="blue" title="Review stored documents" text="Approve, reject or read pages" path="/admin/regulations" />
          <QuickAction icon="radar" tone="violet" title="Compare versions" text="Run Change Radar" path="/admin/change-radar" />
          <QuickAction icon="activity" tone="amber" title="Check the audit log" text="Security and admin events" path="/admin/audit" />
        </section>
      </div>
    </div>
  );
}

function MemberDashboard({ token, user }: { token: string; user: UserProfile }) {
  const hasCohort = Boolean(user.admission_batch && user.programme);
  const isStaff = user.role === "staff";
  const regs = useResource<Regulation[]>(
    hasCohort ? `regulations:cohort:${user.admission_batch}:${user.programme}` : "regulations:none",
    async (signal) =>
      hasCohort ? listCohortRegulations(token, { admission_batch: user.admission_batch!, programme: user.programme! }, signal) : [],
  );
  const updates = useResource(`${token}:approved-updates`, (signal) => listApprovedUpdates(token, signal));

  return (
    <div className="page-stack">
      <PageHeader icon="grid" title={`${greeting()}${user.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}`} subtitle={isStaff ? "Your staff workspace for the cohort assigned to you." : "Everything that applies to your cohort, in one place."} />
      {!hasCohort ? (
        <Notice tone="warning" title="Your cohort isn't set">Ask an administrator to assign your admission batch and programme so applicable regulations can be shown.</Notice>
      ) : null}
      <div className="dash-hero">
        <div className="dash-hero__cohort">
          <span className="dash-hero__label">{isStaff ? "Assigned cohort" : "Your cohort"}</span>
          <strong>{hasCohort ? `Batch ${user.admission_batch}` : "Not assigned"}</strong>
          <span>{user.programme ?? "—"}</span>
        </div>
        <div className="stat-grid stat-grid--2">
          <StatCard label="Applicable regulations" value={value(regs, (d) => d.length)} icon="book" tone="emerald" hint="Approved for this cohort" />
          <StatCard label="Approved updates" value={value(updates, (d) => d.length)} icon="bell" tone="violet" hint="Reviewed by an administrator" />
        </div>
      </div>
      <div className="dash-grid">
        <section className="panel dash-panel">
          <div className="dash-panel__head">
            <h2 className="section-title">Your regulations</h2>
            <button type="button" className="button button--ghost button--compact" onClick={() => navigate("/regulations")}>Open</button>
          </div>
          <Loaded resource={regs}>
            {(list) =>
              list.length ? (
                <ul className="recent-list">
                  {list.map((reg) => (
                    <li key={reg.id}>
                      <span className="recent-list__icon"><Icon name="book" size={16} /></span>
                      <div className="recent-list__main">
                        <strong>{reg.document_name} <span className="tag">{reg.regulation_version}</span></strong>
                        <span>Effective {formatDate(reg.effective_date)} · {reg.total_pages ?? "?"} pages</span>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState title="No approved regulation covers this cohort yet" />
              )
            }
          </Loaded>
        </section>
        <section className="dash-actions" aria-label="Quick actions">
          <h2 className="section-title">Quick actions</h2>
          <QuickAction icon="message" tone="emerald" title="Ask CohortIQ" text="Get a cited answer" path="/" />
          <QuickAction icon="book" tone="amber" title="Read regulations" text="Browse extracted pages" path="/regulations" />
          <QuickAction icon="bell" tone="violet" title="See updates" text="Approved regulation changes" path="/updates" />
        </section>
      </div>
    </div>
  );
}

export function DashboardPage({ token, user }: { token: string; user: UserProfile }) {
  return user.role === "administrator" ? <AdminDashboard token={token} user={user} /> : <MemberDashboard token={token} user={user} />;
}
