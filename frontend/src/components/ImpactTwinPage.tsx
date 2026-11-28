import { useState } from "react";

import { fetchImpactTwin } from "../api/cohortiq";
import type { ImpactAssessment, ImpactClassification, ImpactTwin } from "../api/types";
import { useResource } from "../hooks/useResource";
import { navigate } from "../nav/router";
import { Icon, type IconName } from "./icons";
import { Notice } from "./Notice";
import { SourceDialog, type SourceTarget } from "./PageText";
import { EmptyState, Loaded, PageHeader, formatDate } from "./ui";

const PAGE = 10;

const CLASSES: { key: ImpactClassification; label: string; icon: IconName; tone: string; hint: string }[] = [
  { key: "potential_impact", label: "Potential Impact", icon: "alert", tone: "amber", hint: "Numeric values changed" },
  { key: "requires_review", label: "Requires Review", icon: "eye", tone: "violet", hint: "Added, removed or reworded" },
  { key: "no_direct_impact", label: "No Direct Impact Identified", icon: "checkCircle", tone: "emerald", hint: "Minor wording only" },
];

function Profile({ data }: { data: ImpactTwin }) {
  const regs = data.applicable_regulations;
  const latest = data.latest_update;
  return (
    <section className="twin-profile" aria-label="Your academic profile">
      <div className="twin-profile__item twin-profile__item--hero">
        <span className="twin-profile__label">Admission batch</span>
        <strong>{data.cohort?.admission_batch ?? "Not assigned"}</strong>
      </div>
      <div className="twin-profile__item">
        <span className="twin-profile__label">Programme</span>
        <strong>{data.cohort?.programme ?? "Not assigned"}</strong>
      </div>
      <div className="twin-profile__item">
        <span className="twin-profile__label">Applicable regulation</span>
        <strong>{regs.length ? regs.map((reg) => `${reg.document_name} · ${reg.regulation_version}`).join(", ") : "None approved yet"}</strong>
      </div>
      <div className="twin-profile__item">
        <span className="twin-profile__label">Latest relevant update</span>
        <strong>{latest ? `${latest.document_name} · ${latest.previous_version} → ${latest.new_version}` : "No approved update"}</strong>
        {latest ? <small>Approved {formatDate(latest.reviewed_at)} · {latest.change_count} detected changes</small> : null}
      </div>
    </section>
  );
}

function ImpactCard({ item, onOpen }: { item: ImpactAssessment; onOpen: (target: SourceTarget) => void }) {
  const meta = CLASSES.find((entry) => entry.key === item.classification)!;
  return (
    <article className={`impact-card tone-${meta.tone}`}>
      <header className="impact-card__head">
        <span className="impact-card__icon"><Icon name={meta.icon} size={18} /></span>
        <div className="impact-card__title">
          <h3>{item.clause === "Unnumbered passage" ? "Unnumbered passage" : `Clause ${item.clause}`}</h3>
          <span>{item.document_name} · {item.previous_version} → {item.new_version} · potential {item.change_type}</span>
        </div>
        <span className={`impact-badge impact-badge--${item.classification}`}>{item.classification_label}</span>
      </header>

      <div className="impact-compare">
        <section className="impact-compare__col impact-compare__col--old">
          <span className="impact-compare__label">Previous · {item.previous_version}{item.previous_page != null ? ` · page ${item.previous_page}` : ""}</span>
          <p>{item.previous_text ?? "No matching passage in the previous version."}</p>
          {item.previous_text_truncated ? <small>Excerpt shortened.</small> : null}
        </section>
        <section className="impact-compare__col impact-compare__col--new">
          <span className="impact-compare__label">Revised · {item.new_version}{item.new_page != null ? ` · page ${item.new_page}` : ""}</span>
          <p>{item.new_text ?? "No matching passage in the revised version."}</p>
          {item.new_text_truncated ? <small>Excerpt shortened.</small> : null}
        </section>
      </div>

      <dl className="impact-qa">
        <div>
          <dt>What changed?</dt>
          <dd>
            {item.classification_reason}
            {item.previous_values.length || item.revised_values.length ? (
              <span className="impact-values">
                {item.previous_values.map((value, index) => <span key={`p${index}`} className="impact-value impact-value--old">{value}</span>)}
                <Icon name="arrowRight" size={14} />
                {item.revised_values.map((value, index) => <span key={`n${index}`} className="impact-value impact-value--new">{value}</span>)}
              </span>
            ) : null}
          </dd>
        </div>
        <div>
          <dt>Why does this matter?</dt>
          <dd><ul>{item.implications.map((line, index) => <li key={index}>{line}</li>)}</ul></dd>
        </div>
        <div>
          <dt>Does this apply to my admission batch?</dt>
          <dd>{item.applicability}</dd>
        </div>
        <div>
          <dt>What should I pay attention to?</dt>
          <dd><ul>{item.review_points.map((line, index) => <li key={index}>{line}</li>)}</ul></dd>
        </div>
        <div>
          <dt>Which pages contain the evidence?</dt>
          <dd className="impact-evidence">
            {item.new_page != null ? (
              <button
                type="button"
                className="button button--ghost button--compact"
                onClick={() => onOpen({ regulationId: item.new_regulation_id, page: item.new_page!, title: `${item.document_name} · ${item.new_version}`, excerpt: item.new_text })}
              >
                <Icon name="pages" size={15} /> Open revised page {item.new_page}
              </button>
            ) : null}
            {item.previous_page != null ? (
              <span className="impact-evidence__ref"><Icon name="file" size={14} /> Previous version {item.previous_version}, page {item.previous_page} (excerpt above)</span>
            ) : null}
          </dd>
        </div>
      </dl>
    </article>
  );
}

export function ImpactTwinPage({ token }: { token: string }) {
  const twin = useResource<ImpactTwin>(`${token}:impact-twin`, (signal) => fetchImpactTwin(token, signal));
  const [filter, setFilter] = useState<ImpactClassification | "all">("all");
  const [shown, setShown] = useState(PAGE);
  const [source, setSource] = useState<SourceTarget | null>(null);

  return (
    <div className="page-stack">
      <PageHeader
        icon="target"
        title="My Academic Impact Twin"
        subtitle="See which administrator-approved regulation changes apply to your cohort, what changed, and where the evidence is."
        actions={
          <button type="button" className="button button--ghost" onClick={twin.reload}>
            <Icon name="refresh" size={16} /> Refresh
          </button>
        }
      />
      <Loaded resource={twin}>
        {(data) => {
          const list = filter === "all" ? data.assessments : data.assessments.filter((item) => item.classification === filter);
          return (
            <>
              <Profile data={data} />
              <Notice tone="info" title="Cohort-level assessment, not a personal verdict">
                {data.personalization_note}
              </Notice>

              {!data.cohort ? (
                <EmptyState title="No cohort on this account">
                  The Impact Twin uses the admission batch and programme stored on your account. Ask an administrator to assign them.
                </EmptyState>
              ) : data.summary.total === 0 ? (
                <EmptyState
                  title="No approved regulation changes apply to your cohort"
                  action={<button type="button" className="button button--ghost" onClick={() => navigate("/regulations")}>Read your regulations</button>}
                >
                  Changes appear here only after an administrator approves a Change Radar review for your batch and programme and the revised regulation itself is approved.
                </EmptyState>
              ) : (
                <>
                  <div className="impact-filters" role="group" aria-label="Filter by impact classification">
                    <button type="button" className={`impact-filter${filter === "all" ? " is-active" : ""}`} aria-pressed={filter === "all"} onClick={() => { setFilter("all"); setShown(PAGE); }}>
                      <span className="impact-filter__count">{data.summary.total}</span>
                      <span className="impact-filter__label">All approved changes</span>
                    </button>
                    {CLASSES.map((entry) => (
                      <button
                        key={entry.key}
                        type="button"
                        className={`impact-filter tone-${entry.tone}${filter === entry.key ? " is-active" : ""}`}
                        aria-pressed={filter === entry.key}
                        onClick={() => { setFilter(entry.key); setShown(PAGE); }}
                      >
                        <span className="impact-filter__count">{data.summary[entry.key]}</span>
                        <span className="impact-filter__label"><Icon name={entry.icon} size={14} /> {entry.label}</span>
                        <span className="impact-filter__hint">{entry.hint}</span>
                      </button>
                    ))}
                  </div>
                  {list.length === 0 ? (
                    <EmptyState title="No changes in this category" />
                  ) : (
                    <div className="impact-list">
                      {list.slice(0, shown).map((item) => (
                        <ImpactCard key={`${item.review_id}-${item.change_id}`} item={item} onOpen={setSource} />
                      ))}
                      {list.length > shown ? (
                        <button type="button" className="button button--ghost impact-more" onClick={() => setShown((value) => value + PAGE)}>
                          Show more ({list.length - shown} remaining)
                        </button>
                      ) : null}
                    </div>
                  )}
                </>
              )}
            </>
          );
        }}
      </Loaded>
      {source ? <SourceDialog token={token} source={source} onClose={() => setSource(null)} /> : null}
    </div>
  );
}
