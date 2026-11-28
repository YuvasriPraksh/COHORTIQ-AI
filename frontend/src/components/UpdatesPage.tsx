import { listApprovedUpdates } from "../api/cohortiq";
import type { ChangeReview } from "../api/types";
import { useResource } from "../hooks/useResource";
import { EmptyState, Loaded, PageHeader } from "./ui";

export function UpdatesPage({ token }: { token: string }) {
  const updates = useResource(`${token}:approved-updates`, (signal) => listApprovedUpdates(token, signal));
  return (
    <div className="page-stack">
      <PageHeader icon="bell" title="Approved regulation updates" subtitle="Only administrator-approved reviews that also reference an approved regulation and match your account cohort are shown here." />
      <Loaded resource={updates}>
        {(items: ChangeReview[]) => items.length ? (
          <div className="page-stack">
            {items.map((review) => (
              <section className="panel card" key={review.id}>
                <div className="card__head">
                  <h2 className="card__title">{review.new_document_name} · {review.new_version}</h2>
                  <span className="badge badge--good">Approved update</span>
                </div>
                <p className="muted">Compared with {review.previous_version}. Potential changes were reviewed by an administrator. Verify the cited source pages before relying on them.</p>
                {review.changes.map((change) => (
                  <article className="panel change-item" key={change.id}>
                    <h3>{change.clause} · Potential {change.change_type}</h3>
                    {change.previous_text ? <p><strong>Previous · page {change.previous_page ?? "—"}:</strong> {change.previous_text}</p> : null}
                    {change.new_text ? <p><strong>New · page {change.new_page ?? "—"}:</strong> {change.new_text}</p> : null}
                  </article>
                ))}
              </section>
            ))}
          </div>
        ) : <EmptyState title="No approved updates for your cohort">Updates appear here only after an administrator approves the comparison and the new regulation itself is approved.</EmptyState>}
      </Loaded>
    </div>
  );
}
