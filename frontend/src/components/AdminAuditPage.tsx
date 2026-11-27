import { useState } from "react";

import { listAuditEvents } from "../api/cohortiq";
import type { AuditEventList } from "../api/types";
import { useResource } from "../hooks/useResource";
import { Badge, Card, EmptyState, Loaded, PageHeader, formatDate } from "./ui";

const ACTIONS = [
  "",
  "auth.login_succeeded",
  "auth.login_failed",
  "auth.account_locked",
  "user.created",
  "user.updated",
  "user.role_changed",
  "user.deactivated",
  "user.reactivated",
  "user.unlocked",
  "user.password_reset",
  "user.sessions_revoked",
  "regulation.ingested",
  "regulation.verification_changed",
  "regulation.change_reviewed",
  "query.answered",
  "authorization.denied",
];

function outcomeTone(outcome: "success" | "failure" | "denied") {
  if (outcome === "success") return "good" as const;
  if (outcome === "denied") return "caution" as const;
  return "bad" as const;
}

export function AdminAuditPage({ token }: { token: string }) {
  const [action, setAction] = useState("");
  const [outcome, setOutcome] = useState("");

  const events = useResource<AuditEventList>(
    `audit:${action}:${outcome}`,
    (signal) => listAuditEvents(token, { action: action || undefined, outcome: outcome || undefined, limit: 50 }, signal),
  );

  return (
    <div className="stack">
      <PageHeader
        title="Audit log"
        subtitle="Append-only security and workflow events. Sensitive values, emails, and question text are never recorded."
      />

      <Card
        title="Recorded events"
        actions={
          <div className="filter-bar">
            <label className="filter-bar__field">
              <span className="visually-hidden">Filter by action</span>
              <select value={action} onChange={(e) => setAction(e.target.value)}>
                {ACTIONS.map((item) => (
                  <option key={item || "all"} value={item}>
                    {item || "All actions"}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-bar__field">
              <span className="visually-hidden">Filter by outcome</span>
              <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
                <option value="">All outcomes</option>
                <option value="success">Success</option>
                <option value="failure">Failure</option>
                <option value="denied">Denied</option>
              </select>
            </label>
            <button type="button" className="button button--ghost button--compact" onClick={events.reload}>
              Refresh
            </button>
          </div>
        }
      >
        <Loaded resource={events}>
          {(data) =>
            data.events.length === 0 ? (
              <EmptyState title="No matching audit events" />
            ) : (
              <div className="table-wrap">
                <table className="audit-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Action</th>
                      <th>Outcome</th>
                      <th>Actor</th>
                      <th>Target</th>
                      <th>Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.events.map((ev) => {
                      const detailPairs = Object.entries(ev.details);
                      return (
                        <tr key={ev.id}>
                          <td>{formatDate(ev.occurred_at, true)}</td>
                          <td>
                            <code>{ev.action}</code>
                          </td>
                          <td>
                            <Badge tone={outcomeTone(ev.outcome)}>{ev.outcome}</Badge>
                          </td>
                          <td>
                            {ev.actor_role ?? ev.actor_type}
                            {ev.actor_user_id != null ? ` #${ev.actor_user_id}` : ""}
                          </td>
                          <td>{ev.target_type ? `${ev.target_type} #${ev.target_id ?? "—"}` : "—"}</td>
                          <td>
                            {detailPairs.length
                              ? detailPairs.map(([k, v]) => `${k}: ${String(v)}`).join(" · ")
                              : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )
          }
        </Loaded>
      </Card>
    </div>
  );
}
