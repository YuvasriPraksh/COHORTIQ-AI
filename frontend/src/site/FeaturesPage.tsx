import type { ReactNode } from "react";

import { Icon, type IconName } from "../components/icons";
import { Reveal } from "../components/Reveal";

interface Feature {
  id: string;
  icon: IconName;
  tone: string;
  title: string;
  text: string;
  points: string[];
  visual: ReactNode;
}

const FEATURES: Feature[] = [
  {
    id: "cohort",
    icon: "target",
    tone: "emerald",
    title: "Cohort-aware regulation retrieval",
    text: "Retrieval is limited to approved regulations whose recorded batches and programmes match the signed-in account. The cohort comes from the account on the server, never from the browser.",
    points: ["Batch and programme are read from the authenticated account", "Requests for another cohort are refused (HTTP 403)"],
    visual: (
      <div className="fv-cohort">
        <span className="fv-chip fv-chip--on">Batch 2024 · B.Tech CSE</span>
        <span className="fv-arrow" aria-hidden="true"><Icon name="arrowRight" size={16} /></span>
        <span className="fv-doc fv-doc--on"><Icon name="file" size={14} /> R2023 · approved</span>
        <span className="fv-doc fv-doc--off"><Icon name="ban" size={14} /> R2020 · other cohort</span>
      </div>
    ),
  },
  {
    id: "qa",
    icon: "sparkles",
    tone: "violet",
    title: "AI-powered academic question answering",
    text: "Questions are answered by Google Gemini using only the passages retrieved for your cohort. The model is instructed to stay within that evidence and return a structured answer.",
    points: ["Retrieval runs before the model is called", "Structured output is validated before display"],
    visual: (
      <div className="fv-chat">
        <p className="fv-chat__q">Can I re-register for a failed course?</p>
        <p className="fv-chat__a"><Icon name="sparkles" size={14} /> Grounded in 2 passages from your regulation…</p>
      </div>
    ),
  },
  {
    id: "ingest",
    icon: "upload",
    tone: "teal",
    title: "PDF document ingestion",
    text: "Administrators upload regulation PDFs with a name, version, effective date and the batches and programmes they apply to. Text is extracted page by page and saved together with its page numbers.",
    points: ["PDF only, up to 20 MB and 500 pages per file", "No limit on how many documents are stored"],
    visual: (
      <div className="fv-upload">
        <Icon name="upload" size={22} />
        <span>Regulations_R2023.pdf</span>
        <span className="fv-bar"><i /></span>
        <span className="pill pill--good">35 pages extracted</span>
      </div>
    ),
  },
  {
    id: "citations",
    icon: "pages",
    tone: "amber",
    title: "Page-level citations",
    text: "Each answer lists the document, version and page number it relies on, with the supporting passage, so anyone can verify it against the regulation.",
    points: ["Document name, version and page for every citation", "Read the extracted page text in the app"],
    visual: (
      <div className="fv-cite">
        <Icon name="file" size={16} />
        <div><strong>UG Regulations · R2020</strong><span>“…maintains minimum 75% of attendance.”</span></div>
        <span className="preview__page">Page 13</span>
      </div>
    ),
  },
  {
    id: "evidence",
    icon: "checkCircle",
    tone: "emerald",
    title: "Evidence-backed responses",
    text: "Citations are checked against the passages that were actually retrieved. Unsupported citations are removed and flagged, and an answer is never labelled grounded without at least one valid citation.",
    points: ["Citation validation after generation", "Clear notice when citations were removed"],
    visual: (
      <div className="fv-validate">
        <span className="fv-row fv-row--ok"><Icon name="check" size={14} /> Citation 1 matches page 15</span>
        <span className="fv-row fv-row--ok"><Icon name="check" size={14} /> Citation 2 matches page 17</span>
        <span className="fv-row fv-row--bad"><Icon name="x" size={14} /> Unmatched citation removed</span>
      </div>
    ),
  },
  {
    id: "versions",
    icon: "layers",
    tone: "blue",
    title: "Regulation version management",
    text: "Multiple documents and versions are stored side by side. Each has its own approval status — pending, approved or rejected — and only approved versions are searchable.",
    points: ["New uploads always start as pending", "Approve, reject or return to pending at any time"],
    visual: (
      <div className="fv-versions">
        <span><b>R2020</b><span className="pill pill--good">Approved</span></span>
        <span><b>R2023</b><span className="pill pill--good">Approved</span></span>
        <span><b>R2024 draft</b><span className="pill pill--amber">Pending</span></span>
      </div>
    ),
  },
  {
    id: "radar",
    icon: "radar",
    tone: "amber",
    title: "Change Radar",
    text: "Administrators compare two versions of the same regulation. Additions, removals and modifications are listed with page references from both versions, labelled as potential changes that need review.",
    points: ["Reviews start as “Needs review” — never auto-approved", "Approved updates reach only the selected cohorts"],
    visual: (
      <div className="fv-radar">
        <span className="fv-tag fv-tag--add">+ 73 additions</span>
        <span className="fv-tag fv-tag--mod">~ 118 modifications</span>
        <span className="fv-tag fv-tag--del">− 9 removals</span>
      </div>
    ),
  },
  {
    id: "rbac",
    icon: "lock",
    tone: "rose",
    title: "Role-based access control",
    text: "Students, staff and administrators have different permissions, enforced by the API on every request. Choosing a role on the sign-in screen does not grant it — the account's stored role decides.",
    points: ["No public administrator registration", "Admin APIs refuse student and staff tokens"],
    visual: (
      <div className="fv-roles">
        <span><Icon name="graduation" size={14} /> Student</span>
        <span><Icon name="userCheck" size={14} /> Staff</span>
        <span className="is-admin"><Icon name="shield" size={14} /> Administrator</span>
      </div>
    ),
  },
  {
    id: "unsupported",
    icon: "ban",
    tone: "slate",
    title: "Unsupported-question handling",
    text: "Questions outside academic regulations, or without enough supporting evidence, receive an honest “no grounded answer” instead of a guess. The reason is shown.",
    points: ["Out-of-scope questions are declined", "Low-evidence questions say so rather than invent rules"],
    visual: (
      <div className="fv-decline">
        <p className="fv-chat__q">Who won the 2022 football World Cup?</p>
        <p className="fv-decline__a"><Icon name="info" size={14} /> I can only answer questions about the academic regulations that apply to your cohort.</p>
      </div>
    ),
  },
];

const SHORT: Record<string, string> = {
  cohort: "Cohort retrieval",
  qa: "AI answers",
  ingest: "PDF ingestion",
  citations: "Citations",
  evidence: "Evidence checks",
  versions: "Versions",
  radar: "Change Radar",
  rbac: "Access control",
  unsupported: "Unsupported questions",
};

const LIMITS = [
  { title: "Original PDF download", text: "Only the extracted page text is stored, so the original PDF file cannot be downloaded from CohortIQ." },
  { title: "Staff self-registration", text: "Staff accounts are created by an administrator. There is no public staff sign-up, because emails are not verified." },
  { title: "Email verification", text: "Student registration checks the email domain but does not send a verification email." },
];

export function FeaturesPage() {
  return (
    <>
      <section className="page-hero">
        <div className="page-hero__aurora" aria-hidden="true" />
        <div className="container">
          <Reveal>
            <p className="eyebrow">Features</p>
            <h1>Everything CohortIQ does today</h1>
            <p className="page-hero__text">Nine working capabilities — each one tested end to end against real regulation PDFs. Limitations are listed at the bottom.</p>
          </Reveal>
          <Reveal as="nav" className="jump" aria-label="Jump to a feature" delay={120}>
            {FEATURES.map((feature) => (
              <button key={feature.id} type="button" onClick={() => document.getElementById(`feature-${feature.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })}>
                {SHORT[feature.id] ?? feature.title}
              </button>
            ))}
          </Reveal>
        </div>
      </section>
      <section className="section section--tight">
        <div className="container feature-rows">
          {FEATURES.map((feature, index) => (
            <Reveal key={feature.id} className={`feature-row tone-${feature.tone}${index % 2 ? " feature-row--flip" : ""}`} variant={index % 2 ? "right" : "left"}>
              <article id={`feature-${feature.id}`} className="feature-row__inner">
                <div className="feature-row__copy">
                  <span className="feature-row__icon"><Icon name={feature.icon} size={22} /></span>
                  <div className="feature-row__meta">
                    <span className="feature-row__num">{String(index + 1).padStart(2, "0")}</span>
                    <span className="pill pill--good"><Icon name="check" size={12} /> Available</span>
                  </div>
                  <h2>{feature.title}</h2>
                  <p>{feature.text}</p>
                  <ul>
                    {feature.points.map((point) => (
                      <li key={point}><Icon name="check" size={14} /> {point}</li>
                    ))}
                  </ul>
                </div>
                <div className="feature-row__visual" aria-hidden="true">{feature.visual}</div>
              </article>
            </Reveal>
          ))}
        </div>
      </section>
      <section className="section section--limits">
        <div className="container">
          <Reveal className="section-head section-head--center">
            <p className="eyebrow">Current limitations</p>
            <h2>What CohortIQ does not do (yet)</h2>
          </Reveal>
          <div className="limits">
            {LIMITS.map((item, index) => (
              <Reveal key={item.title} className="limit-card" delay={index * 80}>
                <span className="pill pill--muted">Not available</span>
                <h3>{item.title}</h3>
                <p>{item.text}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
