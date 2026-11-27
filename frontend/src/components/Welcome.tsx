import type { AccountRole } from "../api/types";
import { useEffect, useState } from "react";
import { navigate } from "../nav/router";
import { Notice } from "./Notice";

const roles: { role: AccountRole; title: string; description: string; detail: string }[] = [
  {
    role: "student",
    title: "Student",
    description: "Ask questions about the academic regulations that apply to your cohort.",
    detail: "Ask grounded questions, open approved regulations and verify answers against page evidence. Access is limited to the batch and programme on your account.",
  },
  {
    role: "staff",
    title: "Staff / Teacher",
    description: "Review approved regulations and ask questions for your assigned programme.",
    detail: "Browse approved regulations and ask questions for assigned cohorts. Staff accounts and programme assignments are managed through the authorized process.",
  },
  {
    role: "administrator",
    title: "Administrator",
    description: "Manage accounts, regulations, and supported administrative workflows.",
    detail: "Process regulation PDFs, compare versions in Change Radar, review applicability, and use supported user and audit tools. No public administrator sign-up.",
  },
];

export function Welcome({ notice }: { notice: string | null }) {
  const [darkMode, setDarkMode] = useState(() => {
    try {
      const saved = window.localStorage.getItem("cohortiq.theme");
      if (saved === "dark") return true;
      if (saved === "light") return false;
    } catch {
      // Theme preference is optional; fall back to the operating-system setting.
    }
    return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
  });

  useEffect(() => {
    document.documentElement.dataset.theme = darkMode ? "dark" : "light";
    try {
      window.localStorage.setItem("cohortiq.theme", darkMode ? "dark" : "light");
    } catch {
      // The selected theme remains active for this page even if storage is unavailable.
    }
  }, [darkMode]);

  return (
    <main className="welcome">
      <header className="welcome__top">
        <a className="brand brand--link welcome__brand" href="#/" aria-label="CohortIQ home">
          <span className="brand__mark" aria-hidden="true" />
          CohortIQ
        </a>
        <div className="welcome__top-actions">
          <button type="button" className="button button--ghost button--compact" aria-pressed={darkMode} onClick={() => setDarkMode((value) => !value)}>
            {darkMode ? "☀ Light mode" : "☾ Dark mode"}
          </button>
          <a className="button button--ghost button--compact" href="#/signin" onClick={(event) => { event.preventDefault(); navigate("/signin"); }}>Sign in</a>
          <a className="button button--primary button--compact" href="#/signup" onClick={(event) => { event.preventDefault(); navigate("/signup"); }}>Sign up</a>
        </div>
      </header>
      <section className="welcome__intro" aria-labelledby="welcome-heading">
        <p className="welcome__eyebrow">Academic guidance, grounded in your regulations</p>
        <h1 id="welcome-heading">Know the rule.<br /><span>See the evidence.</span></h1>
        <p>
          CohortIQ helps students and staff find clear answers in the academic regulations that apply to them—with source passages and page references to check.
        </p>
        <a className="welcome__explore" href="#roles">Choose how you use CohortIQ <span aria-hidden="true">↓</span></a>
        <div className="hero-stats" aria-hidden="true">
          <span>Cohort-scoped retrieval</span>
          <span>Page-level citations</span>
          <span>Admin-reviewed Change Radar</span>
        </div>
      </section>
      <figure className="hero-preview" aria-hidden="true">
        <div className="hero-preview__window">
          <div className="hero-preview__bar">
            <i /><i /><i />
            <span>&nbsp;CohortIQ · Ask</span>
            <b>Scoped to your cohort</b>
          </div>
          <div className="hero-preview__body">
            <div className="hero-preview__q">What is the minimum attendance needed to sit the end-semester exam?</div>
            <div className="hero-preview__a">
              Answers come only from the approved regulation for <mark>your admission batch and programme</mark>, with every claim
              linked to the clause and page it came from.
              <div className="hero-preview__cites">
                <span>Regulation · Clause</span>
                <span>Page reference</span>
                <span>Source passage</span>
              </div>
            </div>
          </div>
        </div>
      </figure>
      {notice ? <Notice title={notice} /> : null}
      <section id="roles" className="welcome__roles-section" aria-labelledby="roles-heading">
        <div className="welcome__section-heading">
          <p className="welcome__eyebrow">Your workspace</p>
          <h2 id="roles-heading">Built around your role</h2>
          <p>Choose the account type you already have. Your account permissions—not this selection—determine what you can access.</p>
        </div>
        <div className="welcome__roles" aria-label="Choose your account type">
        {roles.map(({ role, title, description, detail }, index) => (
          <article className="welcome-card" key={role} style={{ ["--card-order" as string]: index }}>
            <span className={`welcome-card__icon welcome-card__icon--${role}`} aria-hidden="true">
              {role === "student" ? "S" : role === "staff" ? "T" : "A"}
            </span>
            <h2>{title}</h2>
            <p>{description}</p>
            <details className="welcome-card__details">
              <summary>What can I do here?</summary>
              <p>{detail}</p>
              {role === "student" ? <p>New student? Use Sign up to create a student account. Staff and administrator accounts are not created through public registration.</p> : null}
            </details>
            <button type="button" className="button button--primary" onClick={() => navigate(`/auth/${role}`)}>
              Continue
              <span aria-hidden="true">→</span>
            </button>
          </article>
        ))}
        </div>
      </section>
      <section className="welcome__product" aria-labelledby="product-heading">
        <div>
          <p className="welcome__eyebrow">Designed for clarity</p>
          <h2 id="product-heading">From question to source page.</h2>
          <p>Ask in plain language. CohortIQ searches approved regulation material for your authenticated cohort, then shows the evidence behind the response. When evidence is missing, it can say so instead of inventing a rule.</p>
        </div>
        <ol className="welcome__steps">
          <li><span>01</span><div><strong>Choose your verified workspace</strong><p>Student, staff, and administrator access are checked against your account.</p></div></li>
          <li><span>02</span><div><strong>Ask about academic regulations</strong><p>Questions use the cohort and programme assigned to your account.</p></div></li>
          <li><span>03</span><div><strong>Check the supporting evidence</strong><p>Review cited source passages and page numbers before relying on an answer.</p></div></li>
        </ol>
      </section>
      <section className="welcome__bottom">
        <p className="welcome__eyebrow">Ready when you are</p>
        <h2>Academic rules, with evidence in view.</h2>
        <div className="welcome__bottom-actions">
          <button type="button" className="button button--primary" onClick={() => navigate("/auth/student")}>Continue as Student</button>
          <button type="button" className="button button--ghost" onClick={() => navigate("/signin")}>Sign in</button>
        </div>
        <p className="welcome__signin">New student? <a href="#/signup" onClick={(event) => { event.preventDefault(); navigate("/signup"); }}>Sign up</a> · Staff and administrator accounts are provisioned securely.</p>
      </section>
      <footer className="welcome__footer">CohortIQ · Evidence-led academic guidance</footer>
    </main>
  );
}
