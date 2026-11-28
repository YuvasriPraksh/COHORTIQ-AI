import { useState } from "react";

import { Icon, type IconName } from "../components/icons";
import { Reveal } from "../components/Reveal";
import { ProductPreview } from "./ProductPreview";

function SectionHead({ eyebrow, title, text, align = "center" }: { eyebrow: string; title: string; text?: string; align?: "center" | "left" }) {
  return (
    <Reveal className={`section-head section-head--${align}`}>
      <p className="eyebrow">{eyebrow}</p>
      <h2>{title}</h2>
      {text ? <p className="section-head__text">{text}</p> : null}
    </Reveal>
  );
}

/* 1 — Hero */
function Hero() {
  return (
    <section className="hero" aria-labelledby="hero-title">
      <div className="hero__aurora" aria-hidden="true">
        <span /><span /><span />
      </div>
      <div className="hero__grid-bg" aria-hidden="true" />
      <div className="container hero__inner">
        <div className="hero__copy">
          <p className="hero__badge"><span className="hero__badge-dot" aria-hidden="true" /> AI-POWERED ACADEMIC REGULATION INTELLIGENCE</p>
          <h1 id="hero-title" className="hero__title">
            <span className="hero__line">Your Academic Rules.</span>{" "}
            <span className="hero__line hero__line--accent">Always Within Reach.</span>
          </h1>
          <p className="hero__text">
            CohortIQ helps students and academic staff understand university regulations through intelligent, cohort-aware search and evidence-backed answers.
          </p>
          <div className="hero__ctas">
            <button
              type="button"
              className="button button--primary button--lg"
              onClick={() => document.getElementById("overview")?.scrollIntoView({ behavior: "smooth", block: "start" })}
            >
              Explore CohortIQ <Icon name="arrowRight" size={18} />
            </button>
            <a className="button button--ghost button--lg" href="#/signup">Get Started</a>
          </div>
          <ul className="hero__facts" aria-label="Highlights">
            <li><Icon name="target" size={16} /> Scoped to your batch &amp; programme</li>
            <li><Icon name="pages" size={16} /> Page-level citations</li>
            <li><Icon name="shield" size={16} /> Admin-approved sources</li>
          </ul>
        </div>
        <div className="hero__visual">
          <ProductPreview />
        </div>
      </div>
    </section>
  );
}

/* 2 — Product overview: the problem CohortIQ solves */
function Overview() {
  return (
    <section id="overview" className="section section--overview">
      <div className="container split">
        <div>
          <SectionHead
            align="left"
            eyebrow="Why it matters"
            title="A correct rule from the wrong regulation is still wrong."
            text="Universities revise their regulations every few years. Attendance thresholds, credit requirements and grading rules can differ between batches and programmes — so a rule that is right for one student can mislead another."
          />
          <Reveal as="ul" className="tick-list" delay={120}>
            <li><Icon name="check" size={16} /> Your authenticated batch and programme decide which regulation is searched.</li>
            <li><Icon name="check" size={16} /> Only documents an administrator has approved are ever used.</li>
            <li><Icon name="check" size={16} /> Every answer shows the document, version and page it came from.</li>
          </Reveal>
        </div>
        <Reveal variant="left" className="cohort-map" delay={100}>
          <div className="cohort-map__card cohort-map__card--muted">
            <span className="cohort-map__ver">R2020</span>
            <strong>UG Regulations 2020</strong>
            <span>Batches 2020 – 2022</span>
          </div>
          <div className="cohort-map__card cohort-map__card--active">
            <span className="cohort-map__ver">R2023</span>
            <strong>B.Tech Regulations 2023</strong>
            <span>Batches 2023 – 2025</span>
            <span className="cohort-map__match"><Icon name="checkCircle" size={14} /> Applies to you</span>
          </div>
          <div className="cohort-map__student">
            <span className="cohort-map__avatar"><Icon name="graduation" size={18} /></span>
            <div>
              <strong>Student · Batch 2024</strong>
              <span>B.Tech CSE</span>
            </div>
          </div>
          <svg className="cohort-map__link" viewBox="0 0 120 60" aria-hidden="true"><path d="M5 55 C 50 55, 60 8, 115 8" /></svg>
        </Reveal>
      </div>
    </section>
  );
}

/* 3 — Core features (bento) */
const CORE: { icon: IconName; title: string; text: string; tone: string; wide?: boolean }[] = [
  { icon: "target", title: "Cohort-aware retrieval", text: "Searches only the approved regulations recorded for your admission batch and programme.", tone: "emerald", wide: true },
  { icon: "sparkles", title: "Grounded AI answers", text: "Gemini writes the answer only from retrieved passages, then each citation is validated.", tone: "violet" },
  { icon: "pages", title: "Page-level citations", text: "Document, version and page number with the supporting passage.", tone: "amber" },
  { icon: "upload", title: "PDF ingestion", text: "Administrators upload regulation PDFs; text is extracted page by page.", tone: "teal" },
  { icon: "lock", title: "Role-based access", text: "Student, staff and administrator permissions are checked by the server on every request.", tone: "rose" },
  { icon: "radar", title: "Change Radar", text: "Compare two versions of a regulation and review potential changes before anyone sees them.", tone: "blue", wide: true },
];

function CoreFeatures() {
  return (
    <section className="section section--features">
      <div className="container">
        <SectionHead eyebrow="Core capabilities" title="Built for precision, not guesswork" text="Six capabilities work together so an answer is only shown when the right regulation supports it." />
        <div className="bento">
          {CORE.map((item, index) => (
            <Reveal key={item.title} className={`bento__card tone-${item.tone}${item.wide ? " bento__card--wide" : ""}`} delay={index * 70}>
              <span className="bento__icon"><Icon name={item.icon} size={22} /></span>
              <h3>{item.title}</h3>
              <p>{item.text}</p>
            </Reveal>
          ))}
        </div>
        <Reveal className="center-link">
          <a className="text-link" href="#/features">See every feature in detail <Icon name="arrowRight" size={16} /></a>
        </Reveal>
      </div>
    </section>
  );
}

/* 4 — How it works (compact) */
const FLOW: { icon: IconName; title: string; text: string }[] = [
  { icon: "upload", title: "Upload", text: "An administrator adds a regulation PDF with its batches and programmes." },
  { icon: "cpu", title: "Extract", text: "Text is extracted page by page and stored, pending approval." },
  { icon: "search", title: "Retrieve", text: "A question searches approved passages for the asker's cohort." },
  { icon: "quote", title: "Answer", text: "A grounded answer is returned with validated page citations." },
];

function HowItWorksStrip() {
  return (
    <section className="section section--flow">
      <div className="container">
        <SectionHead eyebrow="How CohortIQ works" title="From PDF to cited answer in four steps" />
        <ol className="flow">
          {FLOW.map((step, index) => (
            <Reveal as="li" key={step.title} className="flow__step" delay={index * 110}>
              <span className="flow__num">{String(index + 1).padStart(2, "0")}</span>
              <span className="flow__icon"><Icon name={step.icon} size={22} /></span>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
            </Reveal>
          ))}
        </ol>
        <Reveal className="center-link">
          <a className="text-link" href="#/how-it-works">Walk through the full workflow <Icon name="arrowRight" size={16} /></a>
        </Reveal>
      </div>
    </section>
  );
}

/* 5 — Student experience */
function StudentExperience() {
  return (
    <section className="section section--student">
      <div className="container split">
        <div>
          <SectionHead
            align="left"
            eyebrow="For students"
            title="Ask in plain language. Get the rule that applies to you."
            text="Sign up with your student email, and your batch and programme are stored on your account. You never pick a regulation by hand — CohortIQ does it for you."
          />
          <Reveal as="ul" className="feature-list" delay={100}>
            <li><span className="feature-list__icon tone-emerald"><Icon name="message" size={18} /></span><div><strong>Natural questions</strong><span>“Can I write the exam with 70% attendance?”</span></div></li>
            <li><span className="feature-list__icon tone-amber"><Icon name="book" size={18} /></span><div><strong>Your regulations, readable</strong><span>Open the approved documents for your cohort, page by page.</span></div></li>
            <li><span className="feature-list__icon tone-violet"><Icon name="bell" size={18} /></span><div><strong>Approved updates</strong><span>See reviewed regulation changes that affect your cohort.</span></div></li>
          </Reveal>
        </div>
        <Reveal variant="left" className="mock mock--ask" delay={120}>
          <div className="mock__head">
            <strong>Ask CohortIQ</strong>
            <span className="pill pill--soft"><Icon name="graduation" size={13} /> Batch 2024 · B.Tech CSE</span>
          </div>
          <div className="mock__input">What is the minimum attendance to sit the end-semester exam?<span className="mock__caret" aria-hidden="true" /></div>
          <div className="mock__chips">
            <span>Attendance rules</span><span>Re-registration</span><span>Grading</span>
          </div>
          <div className="mock__foot"><Icon name="shield" size={14} /> Searches only your approved regulation</div>
        </Reveal>
      </div>
    </section>
  );
}

/* 6 — Staff experience */
function StaffExperience() {
  return (
    <section className="section section--staff">
      <div className="container split split--reverse">
        <div>
          <SectionHead
            align="left"
            eyebrow="For staff & teachers"
            title="Answer student queries with the source in hand."
            text="Staff accounts are created by an administrator and assigned to a cohort. Staff ask questions and read approved regulations within that assignment — nothing more."
          />
          <Reveal as="ul" className="tick-list" delay={100}>
            <li><Icon name="check" size={16} /> Same grounded answers students receive, for the assigned cohort.</li>
            <li><Icon name="check" size={16} /> Access to approved regulation text for that cohort.</li>
            <li><Icon name="check" size={16} /> No upload, approval or user-management permissions.</li>
          </Reveal>
        </div>
        <Reveal variant="right" className="mock mock--staff" delay={120}>
          <div className="mock__head">
            <strong>Staff workspace</strong>
            <span className="pill pill--violet"><Icon name="userCheck" size={13} /> Staff / Teacher</span>
          </div>
          <div className="assign">
            <span className="assign__label">Assigned cohort</span>
            <strong>Batch 2022 · B.Tech AI &amp; DS</strong>
          </div>
          <ul className="doc-rows">
            <li><Icon name="file" size={16} /><span>UG Regulations · R2020</span><span className="pill pill--good">Approved</span></li>
            <li className="is-locked"><Icon name="lock" size={16} /><span>Other cohorts' regulations</span><span className="pill pill--muted">No access</span></li>
          </ul>
        </Reveal>
      </div>
    </section>
  );
}

/* 7 — Evidence & citations (interactive) */
const PASSAGES = [
  { n: 1, page: 13, label: "Clause 8.1.1", text: "The student is permitted to appear for End Semester Examinations only if he/she maintains minimum 75% of attendance." },
  { n: 2, page: 13, label: "Clause 8.1.1 (condonation)", text: "Attendance of 60% or more and less than 75% may be considered for medical reasons or approved sports, NCC or NSS activities." },
];

function EvidenceSection() {
  const [active, setActive] = useState(1);
  const passage = PASSAGES.find((item) => item.n === active)!;
  return (
    <section className="section section--evidence">
      <div className="container">
        <SectionHead
          eyebrow="Evidence & citation system"
          title="Every claim points to a page you can check"
          text="Citations are validated against the passages that were actually retrieved. If a citation doesn't match, it is removed and you are told. Try it: select a citation."
        />
        <Reveal className="evidence-demo" variant="zoom">
          <div className="evidence-demo__answer">
            <span className="pill pill--good"><Icon name="checkCircle" size={13} /> Grounded answer</span>
            <p>
              You need at least 75% attendance to write the end-semester examinations
              <button type="button" className={`cite-chip${active === 1 ? " is-active" : ""}`} onClick={() => setActive(1)} aria-pressed={active === 1}>1</button>.
              Between 60% and 75% may be condoned for specific reasons
              <button type="button" className={`cite-chip${active === 2 ? " is-active" : ""}`} onClick={() => setActive(2)} aria-pressed={active === 2}>2</button>.
            </p>
            <p className="evidence-demo__note"><Icon name="info" size={14} /> Example from the R2020 UG Regulations, as answered by CohortIQ.</p>
          </div>
          <div className="evidence-demo__source" aria-live="polite">
            <div className="evidence-demo__source-head">
              <Icon name="file" size={16} />
              <strong>UG Regulations · R2020</strong>
              <span className="preview__page">Page {passage.page}</span>
            </div>
            <span className="evidence-demo__clause">{passage.label}</span>
            <blockquote key={passage.n}>{passage.text}</blockquote>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/* 8 — Regulation management & Change Radar */
function ManagementSection() {
  const stages = ["Uploaded", "Text extracted", "Pending review", "Approved"];
  return (
    <section className="section section--manage">
      <div className="container split">
        <div>
          <SectionHead
            align="left"
            eyebrow="Regulation management"
            title="Nothing reaches students without an administrator's approval."
            text="New documents start as pending. Change Radar compares two versions of the same regulation clause by clause, labels each difference as a potential change, and keeps it hidden until it is reviewed."
          />
          <Reveal className="stages" delay={80}>
            {stages.map((stage, index) => (
              <span key={stage} className={`stages__item stages__item--${index}`}>
                <i aria-hidden="true">{index + 1}</i>
                {stage}
              </span>
            ))}
          </Reveal>
        </div>
        <Reveal variant="left" className="diff-card" delay={120}>
          <div className="diff-card__head">
            <span className="diff-card__title"><Icon name="radar" size={16} /> Change Radar</span>
            <span className="pill pill--amber">Potential changes — review required</span>
          </div>
          <div className="diff-card__row">
            <span className="diff-card__type diff-card__type--mod">Modification</span>
            <span className="diff-card__clause">Movement to next semester</span>
          </div>
          <div className="diff-card__cols">
            <div><span>Previous · page 13</span><p>Clause 8.2 — minimum attendance requirement…</p></div>
            <div><span>New · page 22</span><p>Clause 10.2 — minimum attendance requirement…</p></div>
          </div>
          <div className="diff-card__foot">
            <span><Icon name="clock" size={14} /> Needs review</span>
            <span className="diff-card__hint">Students see it only after approval</span>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/* 9 — Why CohortIQ */
const WHY: [string, boolean, boolean][] = [
  ["Uses the regulation for your batch & programme", false, true],
  ["Cites document, version and page", false, true],
  ["Says so when the regulations don't cover a question", false, true],
  ["Uses only administrator-approved documents", false, true],
  ["Server-side role and cohort checks", false, true],
];

function WhySection() {
  return (
    <section className="section section--why">
      <div className="container">
        <SectionHead eyebrow="Why CohortIQ?" title="Built differently from a general chatbot" text="General AI assistants answer from everything they have seen. CohortIQ answers only from what applies to you." />
        <Reveal className="compare" variant="zoom">
          <div className="compare__row compare__row--head">
            <span />
            <span>General AI chatbot</span>
            <span className="compare__us">CohortIQ</span>
          </div>
          {WHY.map(([label, generic, ours]) => (
            <div className="compare__row" key={label}>
              <span>{label}</span>
              <span className={generic ? "compare__yes" : "compare__no"}>
                <Icon name={generic ? "check" : "x"} size={16} label={generic ? "Yes" : "Not guaranteed"} />
              </span>
              <span className={`compare__us ${ours ? "compare__yes" : "compare__no"}`}>
                <Icon name={ours ? "check" : "x"} size={16} label={ours ? "Yes" : "No"} />
              </span>
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}

/* 10 — Final call to action */
function FinalCta() {
  return (
    <section className="section section--cta">
      <div className="container">
        <Reveal className="cta-band" variant="zoom">
          <div className="cta-band__glow" aria-hidden="true" />
          <h2>Bring clarity to every academic rule.</h2>
          <p>Create a student account with your college email and ask your first question in under a minute.</p>
          <div className="cta-band__actions">
            <a className="button button--light button--lg" href="#/signup">Get Started <Icon name="arrowRight" size={18} /></a>
            <a className="text-link text-link--light" href="#/how-it-works">See how it works</a>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

export function LandingPage({ notice }: { notice?: string | null }) {
  return (
    <>
      {notice ? <div className="container site-notice" role="status">{notice}</div> : null}
      <Hero />
      <Overview />
      <CoreFeatures />
      <HowItWorksStrip />
      <StudentExperience />
      <StaffExperience />
      <EvidenceSection />
      <ManagementSection />
      <WhySection />
      <FinalCta />
    </>
  );
}
