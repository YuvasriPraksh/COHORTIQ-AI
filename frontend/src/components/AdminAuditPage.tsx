import { useEffect, useMemo, useState } from "react";

import { listAuditEvents } from "../api/cohortiq";
import type { AuditEvent, AuditEventList } from "../api/types";
import { useResource } from "../hooks/useResource";
import { Icon, type IconName } from "./icons";
import { Badge, Drawer, EmptyState, Loaded, PageHeader, StatCard, type Tone } from "./ui";

const PAGE_SIZE = 25;

type Category = "auth" | "security" | "document" | "approval" | "account" | "query";

const ACTIONS: Record<string, { label: string; category: Category }> = {
  "auth.login_succeeded": { label: "Sign-in succeeded", category: "auth" },
  "auth.login_failed": { label: "Sign-in failed", category: "auth" },
  "auth.account_locked": { label: "Account locked", category: "security" },
  "authorization.denied": { label: "Access denied", category: "security" },
  "user.created": { label: "Account created", category: "account" },
  "user.updated": { label: "Account updated", category: "account" },
  "user.role_changed": { label: "Role changed", category: "account" },
  "user.deactivated": { label: "Account deactivated", category: "account" },
  "user.reactivated": { label: "Account reactivated", category: "account" },
  "user.unlocked": { label: "Account unlocked", category: "account" },
  "user.password_reset": { label: "Password reset", category: "account" },
  "user.sessions_revoked": { label: "Sessions revoked", category: "account" },
  "regulation.ingested": { label: "Regulation uploaded", category: "document" },
  "regulation.verification_changed": { label: "Approval status changed", category: "approval" },
  "regulation.change_reviewed": { label: "Change Radar review", category: "approval" },
  "query.answered": { label: "Question answered", category: "query" },
};

const CATEGORY: Record<Category, { icon: IconName; name: string }> = {
  auth: { icon: "key", name: "Authentication" },
  security: { icon: "shield", name: "Security" },
  document: { icon: "file", name: "Documents" },
  approval: { icon: "checkCircle", name: "Approvals" },
  account: { icon: "users", name: "Accounts" },
  query: { icon: "message", name: "Questions" },
};

const OUTCOME: Record<AuditEvent["outcome"], { label: string; tone: Tone }> = {
  success: { label: "Success", tone: "good" },
  denied: { label: "Denied", tone: "bad" },
  failure: { label: "Failed", tone: "caution" },
};

const SENSITIVE_KEY = /pass|token|secret|key|hash|authorization|cookie/i;

function describe(action: string) {
  return ACTIONS[action] ?? { label: action, category: "query" as Category };
}

function formatStamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function actorText(ev: AuditEvent): string {
  if (ev.actor_type === "anonymous") return "Anonymous";
  if (ev.actor_type === "cli") return "Command line";
  if (ev.actor_type === "system") return "System";
  const role = ev.actor_role ? ev.actor_role[0]!.toUpperCase() + ev.actor_role.slice(1) : "User";
  return ev.actor_user_id != null ? `${role} #${ev.actor_user_id}` : role;
}

function targetText(ev: AuditEvent): string {
  if (!ev.target_type) return "—";
  const name = ev.target_type === "regulation" ? "Regulation" : "User";
  return `${name} #${ev.target_id ?? "—"}`;
}

function detailValue(key: string, value: unknown): string {
  if (SENSITIVE_KEY.test(key)) return "••• (hidden)";
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function humanKey(key: string): string {
  return key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function useCount(key: string, token: string, params: Parameters<typeof listAuditEvents>[1]) {
  return useResource<number>(key, async (signal) => (await listAuditEvents(token, { ...params, limit: 1 }, signal)).total);
}

function EventDetails({ ev, onClose }: { ev: AuditEvent; onClose: () => void }) {
  const info = describe(ev.action);
  const outcome = OUTCOME[ev.outcome];
  const details = Object.entries(ev.details ?? {});
  return (
    <Drawer title={info.label} subtitle={<code>{ev.action}</code>} onClose={onClose}>
      <div className={`event-hero cat-${info.category}`}>
        <span className="event-hero__icon"><Icon name={CATEGORY[info.category].icon} size={22} /></span>
        <div>
          <span className="event-hero__cat">{CATEGORY[info.category].name}</span>
          <Badge tone={outcome.tone}>{outcome.label}</Badge>
        </div>
      </div>
      <dl className="detail-list">
        <div><dt>Event ID</dt><dd>#{ev.id}</dd></div>
        <div><dt>Timestamp</dt><dd>{formatStamp(ev.occurred_at)}<small className="muted block">{ev.occurred_at}</small></dd></div>
        <div><dt>Actor</dt><dd>{actorText(ev)}<small className="muted block">Type: {ev.actor_type}{ev.actor_role ? ` · Role: ${ev.actor_role}` : ""}</small></dd></div>
        <div><dt>Target</dt><dd>{targetText(ev)}</dd></div>
      </dl>
      <h3 className="drawer__section">Recorded details</h3>
      {details.length ? (
        <dl className="kv-list">
          {details.map(([key, value]) => (
            <div key={key}>
              <dt>{humanKey(key)}</dt>
              <dd><code>{detailValue(key, value)}</code></dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="muted">No additional details were recorded for this event.</p>
      )}
      <p className="drawer__note"><Icon name="lock" size={14} /> The audit log never records passwords, tokens, email addresses or question text.</p>
    </Drawer>
  );
}

export function AdminAuditPage({ token }: { token: string }) {
  const [tick, setTick] = useState(0);
  const [cutoff, setCutoff] = useState(() => new Date(Date.now() - 24 * 3600 * 1000).toISOString());
  const [action, setAction] = useState("");
  const [outcome, setOutcome] = useState("");
  const [targetType, setTargetType] = useState("");
  const [actorId, setActorId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [openId, setOpenId] = useState<number | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const actorNumber = /^\d+$/.test(actorId.trim()) && Number(actorId) > 0 ? Number(actorId) : undefined;
  const actorInvalid = actorId.trim() !== "" && actorNumber === undefined;
  const occurredAfter = from ? new Date(`${from}T00:00:00`).toISOString() : undefined;
  const occurredBefore = to ? new Date(`${to}T23:59:59.999`).toISOString() : undefined;
  const rangeInvalid = Boolean(from && to && from > to);

  const filters = {
    action: action || undefined,
    outcome: outcome || undefined,
    target_type: targetType || undefined,
    actor_user_id: actorNumber,
    occurred_after: rangeInvalid ? undefined : occurredAfter,
    occurred_before: rangeInvalid ? undefined : occurredBefore,
  };
  const filterKey = JSON.stringify(filters);

  const events = useResource<AuditEventList>(`audit:${filterKey}:${offset}:${tick}`, (signal) =>
    listAuditEvents(token, { ...filters, limit: PAGE_SIZE, offset }, signal),
  );
  const total = useCount(`audit-count:all:${tick}`, token, {});
  const success = useCount(`audit-count:success:${tick}`, token, { outcome: "success" });
  const denied = useCount(`audit-count:denied:${tick}`, token, { outcome: "denied" });
  const denied24 = useCount(`audit-count:denied24:${cutoff}`, token, { outcome: "denied", occurred_after: cutoff });
  const failed24 = useCount(`audit-count:failed24:${cutoff}`, token, { outcome: "failure", occurred_after: cutoff });

  useEffect(() => {
    if (events.status === "ready") setUpdatedAt(new Date());
  }, [events.status, events.data]);

  useEffect(() => setOffset(0), [filterKey]);

  function refresh() {
    setCutoff(new Date(Date.now() - 24 * 3600 * 1000).toISOString());
    setTick((value) => value + 1);
  }

  function reset() {
    setAction("");
    setOutcome("");
    setTargetType("");
    setActorId("");
    setFrom("");
    setTo("");
    setSearch("");
  }

  const filtersActive = Boolean(action || outcome || targetType || actorId || from || to || search);
  const page = events.status === "ready" ? events.data : null;

  const visible = useMemo(() => {
    if (!page) return [];
    const term = search.trim().toLowerCase();
    if (!term) return page.events;
    return page.events.filter((ev) =>
      [describe(ev.action).label, ev.action, ev.outcome, actorText(ev), targetText(ev), JSON.stringify(ev.details ?? {})]
        .join(" ")
        .toLowerCase()
        .includes(term),
    );
  }, [page, search]);

  const security24 = denied24.status === "ready" && failed24.status === "ready" ? denied24.data + failed24.data : null;
  const show = (r: { status: string; data: number | null }) => (r.status === "ready" ? r.data : r.status === "error" ? "!" : "—");
  const openEvent = page?.events.find((ev) => ev.id === openId) ?? null;

  return (
    <div className="page-stack">
      <PageHeader
        icon="activity"
        title="Audit Log"
        subtitle="Monitor account activity, security events and administrative operations across CohortIQ."
        actions={
          <>
            {updatedAt ? <span className="updated-at" role="status">Updated {updatedAt.toLocaleTimeString()}</span> : null}
            <button type="button" className="button button--ghost" onClick={refresh}>
              <Icon name="refresh" size={16} /> Refresh
            </button>
          </>
        }
      />

      <div className="stat-grid">
        <StatCard label="Total recorded events" value={show(total)} icon="activity" tone="blue" />
        <StatCard label="Successful actions" value={show(success)} icon="checkCircle" tone="emerald" />
        <StatCard label="Denied actions" value={show(denied)} icon="ban" tone="rose" />
        <StatCard label="Security events · 24h" value={security24 ?? "—"} icon="shield" tone="amber" hint="Denied or failed in the last 24 hours" />
      </div>

      <section className="panel table-panel">
        <div className="toolbar toolbar--audit">
          <label className="toolbar__search">
            <Icon name="search" size={16} />
            <span className="visually-hidden">Search events on this page</span>
            <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search events on this page" />
          </label>
          <label className="select">
            <span className="visually-hidden">Filter by action</span>
            <select value={action} onChange={(e) => setAction(e.target.value)}>
              <option value="">All actions</option>
              {Object.entries(CATEGORY).map(([category, meta]) => (
                <optgroup key={category} label={meta.name}>
                  {Object.entries(ACTIONS)
                    .filter(([, info]) => info.category === category)
                    .map(([code, info]) => <option key={code} value={code}>{info.label}</option>)}
                </optgroup>
              ))}
            </select>
          </label>
          <label className="select">
            <span className="visually-hidden">Filter by outcome</span>
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              <option value="">All outcomes</option>
              <option value="success">Success</option>
              <option value="denied">Denied</option>
              <option value="failure">Failed</option>
            </select>
          </label>
          <label className="select">
            <span className="visually-hidden">Filter by target type</span>
            <select value={targetType} onChange={(e) => setTargetType(e.target.value)}>
              <option value="">Any target</option>
              <option value="user">User accounts</option>
              <option value="regulation">Regulations</option>
            </select>
          </label>
          <label className="mini-field">
            <span>Actor ID</span>
            <input inputMode="numeric" value={actorId} onChange={(e) => setActorId(e.target.value)} placeholder="Any" aria-invalid={actorInvalid} />
          </label>
          <label className="mini-field">
            <span>From</span>
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-invalid={rangeInvalid} />
          </label>
          <label className="mini-field">
            <span>To</span>
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-invalid={rangeInvalid} />
          </label>
          {filtersActive ? (
            <button type="button" className="button button--ghost button--compact" onClick={reset}>Reset filters</button>
          ) : null}
        </div>
        {actorInvalid ? <p className="field-error">Actor ID must be a positive whole number; the filter is ignored until it is.</p> : null}
        {rangeInvalid ? <p className="field-error">The “From” date is after the “To” date; the date filter is ignored.</p> : null}

        <Loaded resource={events}>
          {(data) =>
            data.events.length === 0 ? (
              filtersActive ? (
                <EmptyState title="No events match these filters" action={<button type="button" className="button button--ghost" onClick={reset}>Reset filters</button>} />
              ) : (
                <EmptyState title="No audit events recorded yet">Sign-ins, uploads, approvals and account changes will appear here.</EmptyState>
              )
            ) : (
              <>
                <div className="table-wrap table-wrap--sticky">
                  <table className="data-table data-table--audit">
                    <thead>
                      <tr>
                        <th scope="col">Timestamp</th>
                        <th scope="col">Action</th>
                        <th scope="col">Outcome</th>
                        <th scope="col">Actor</th>
                        <th scope="col">Target</th>
                        <th scope="col">Details</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visible.map((ev) => {
                        const info = describe(ev.action);
                        const outcomeInfo = OUTCOME[ev.outcome];
                        const pairs = Object.entries(ev.details ?? {});
                        return (
                          <tr key={ev.id} className="is-clickable" onClick={() => setOpenId(ev.id)}>
                            <td data-label="Timestamp" className="nowrap mono">{formatStamp(ev.occurred_at)}</td>
                            <td data-label="Action">
                              <span className={`event-action cat-${info.category}`}>
                                <span className="event-action__icon"><Icon name={CATEGORY[info.category].icon} size={15} /></span>
                                <span>
                                  <strong>{info.label}</strong>
                                  <code>{ev.action}</code>
                                </span>
                              </span>
                            </td>
                            <td data-label="Outcome"><Badge tone={outcomeInfo.tone}>{outcomeInfo.label}</Badge></td>
                            <td data-label="Actor" className="nowrap">{actorText(ev)}</td>
                            <td data-label="Target" className="nowrap">{targetText(ev)}</td>
                            <td data-label="Details">
                              <div className="details-cell">
                                <span className="details-cell__text">
                                  {pairs.length ? pairs.slice(0, 2).map(([k, v]) => `${humanKey(k)}: ${detailValue(k, v)}`).join(" · ") : "—"}
                                </span>
                                <button
                                  type="button"
                                  className="icon-button icon-button--sm"
                                  aria-label={`View details of event ${ev.id}`}
                                  title="View details"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    setOpenId(ev.id);
                                  }}
                                >
                                  <Icon name="eye" size={15} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {visible.length === 0 ? <EmptyState title="No events on this page match your search" /> : null}
                </div>
                <div className="pager">
                  <span>
                    Showing {data.offset + 1}–{data.offset + data.events.length} of {data.total} events
                  </span>
                  <div className="button-row">
                    <button type="button" className="button button--ghost button--compact" disabled={data.offset === 0} onClick={() => setOffset(Math.max(0, data.offset - PAGE_SIZE))}>
                      Previous
                    </button>
                    <button type="button" className="button button--ghost button--compact" disabled={data.offset + data.events.length >= data.total} onClick={() => setOffset(data.offset + PAGE_SIZE)}>
                      Next
                    </button>
                  </div>
                </div>
              </>
            )
          }
        </Loaded>
      </section>

      {openEvent ? <EventDetails ev={openEvent} onClose={() => setOpenId(null)} /> : null}
    </div>
  );
}
