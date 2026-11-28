import { Icon, type IconName } from "../components/icons";
import { Reveal } from "../components/Reveal";

const PRINCIPLES: { icon: IconName; tone: string; title: string; text: string }[] = [
  { icon: "pages", tone: "amber", title: "Evidence first", text: "If CohortIQ can't point to the page, it doesn't present the answer as established regulation." },
  { icon: "target", tone: "emerald", title: "Cohort precision", text: "The right rule depends on who is asking. Batch and programme are part of every search." },
  { icon: "userCheck", tone: "violet", title: "Human approval", text: "Documents and detected changes are reviewed by an administrator before students can see them." },
  { icon: "lock", tone: "blue", title: "Privacy-aware auditing", text: "Security and workflow events are logged without passwords, emails or question text." },
];

const STACK = [
  { name: "React + TypeScript", role: "Web interface" },
  { name: "FastAPI", role: "API, authentication, authorization" },
  { name: "SQLite", role: "Regulations, pages, accounts, audit log" },
  { name: "PyMuPDF", role: "PDF text extraction" },
  { name: "Google Gemini", role: "Grounded answer generation" },
];

export function AboutPage() {
  return (
    <>
      <section className="page-hero">
        <div className="page-hero__aurora page-hero__aurora--violet" aria-hidden="true" />
        <div className="container">
          <Reveal>
            <p className="eyebrow">About</p>
            <h1>Making academic regulations answerable — correctly.</h1>
            <p className="page-hero__text">
              CohortIQ is an academic regulation assistant. It answers students' and staff members' questions from the regulation documents that
              apply to their admission batch and programme, and shows the evidence for every answer.
            </p>
          </Reveal>
        </div>
      </section>

      <section className="section section--tight">
        <div className="container split split--top">
          <Reveal className="about-story">
            <h2>The problem we set out to solve</h2>
            <p>
              Regulation documents are long, revised every few years, and different for different batches. Students often search a PDF that
              doesn't apply to them, or ask a general chatbot that answers confidently without a source.
            </p>
            <p>
              CohortIQ keeps the answer tied to the right document. It searches only approved regulations recorded for the asker's cohort, cites
              the page, and declines when the documents don't support an answer.
            </p>
          </Reveal>
          <Reveal className="about-scope" variant="left" delay={100}>
            <h3>What CohortIQ is — and isn't</h3>
            <ul>
              <li className="is-yes"><Icon name="check" size={16} /> A way to find and understand the rules that apply to you</li>
              <li className="is-yes"><Icon name="check" size={16} /> A tool for administrators to curate and review regulations</li>
              <li className="is-no"><Icon name="x" size={16} /> Not an official decision-maker on academic matters</li>
              <li className="is-no"><Icon name="x" size={16} /> Not a replacement for checking the cited page</li>
            </ul>
          </Reveal>
        </div>
      </section>

      <section className="section section--principles">
        <div className="container">
          <Reveal className="section-head section-head--center">
            <p className="eyebrow">Principles</p>
            <h2>What guides the design</h2>
          </Reveal>
          <div className="principles">
            {PRINCIPLES.map((item, index) => (
              <Reveal key={item.title} className={`principle tone-${item.tone}`} delay={index * 80}>
                <span className="principle__icon"><Icon name={item.icon} size={22} /></span>
                <h3>{item.title}</h3>
                <p>{item.text}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="section section--tight">
        <div className="container">
          <Reveal className="section-head section-head--center">
            <p className="eyebrow">Technology</p>
            <h2>What CohortIQ is built with</h2>
          </Reveal>
          <Reveal className="stack-list" variant="zoom">
            {STACK.map((item) => (
              <div key={item.name} className="stack-list__item">
                <strong>{item.name}</strong>
                <span>{item.role}</span>
              </div>
            ))}
          </Reveal>
        </div>
      </section>
    </>
  );
}
