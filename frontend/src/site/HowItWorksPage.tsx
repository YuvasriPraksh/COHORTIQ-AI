import { Icon, type IconName } from "../components/icons";
import { Reveal } from "../components/Reveal";

const STEPS: { icon: IconName; who: "Administrator" | "CohortIQ" | "Student / Staff"; title: string; text: string; detail: string }[] = [
  {
    icon: "upload",
    who: "Administrator",
    title: "Upload academic regulation documents",
    text: "An administrator uploads a regulation PDF and records its document name, version, effective date, and the admission batches and programmes it applies to.",
    detail: "PDF files up to 20 MB and 500 pages each. Any number of documents and versions can be stored.",
  },
  {
    icon: "cpu",
    who: "CohortIQ",
    title: "Extract and process document content",
    text: "The PDF is read page by page and its text is extracted. If the file can't be read, the upload fails with a clear error and nothing is saved.",
    detail: "Extraction results report how many pages succeeded and how many need attention.",
  },
  {
    icon: "database",
    who: "CohortIQ",
    title: "Store metadata and page information",
    text: "The document's metadata and every page's text are saved together in one transaction, keeping the page numbers used later for citations. The new document is marked pending.",
    detail: "Pending documents are never searched. An administrator must approve them first.",
  },
  {
    icon: "graduation",
    who: "Student / Staff",
    title: "Identify the signed-in cohort",
    text: "When a student or staff member asks a question, CohortIQ reads their admission batch and programme from their account on the server — not from anything the browser sends.",
    detail: "Asking about a different cohort is refused.",
  },
  {
    icon: "search",
    who: "CohortIQ",
    title: "Retrieve relevant approved passages",
    text: "The question is matched against passages from approved regulations that apply to that cohort. Questions outside academic regulations are routed away before any answer is generated.",
    detail: "If no passage is a strong enough match, CohortIQ says there isn't enough evidence.",
  },
  {
    icon: "sparkles",
    who: "CohortIQ",
    title: "Generate an evidence-grounded response",
    text: "Gemini writes the answer using only the retrieved passages. Every citation in the response is then checked against those passages, and unsupported ones are removed.",
    detail: "An answer is only labelled grounded when at least one citation survives validation.",
  },
  {
    icon: "pages",
    who: "Student / Staff",
    title: "Display citations and page references",
    text: "The answer appears with the document, version and page for each citation and the supporting passage, so the reader can open the page and check it.",
    detail: "Extracted page text can be read inside CohortIQ.",
  },
];

const WHO_TONE = { Administrator: "violet", CohortIQ: "emerald", "Student / Staff": "amber" } as const;

export function HowItWorksPage() {
  return (
    <>
      <section className="page-hero">
        <div className="page-hero__aurora page-hero__aurora--teal" aria-hidden="true" />
        <div className="container">
          <Reveal>
            <p className="eyebrow">How it works</p>
            <h1>From a regulation PDF to a cited answer</h1>
            <p className="page-hero__text">Seven steps, three participants. Administrators curate the documents, CohortIQ does the processing, and students and staff get answers they can verify.</p>
          </Reveal>
          <Reveal className="legend" delay={120}>
            {Object.entries(WHO_TONE).map(([who, tone]) => (
              <span key={who} className={`legend__item tone-${tone}`}><i aria-hidden="true" />{who}</span>
            ))}
          </Reveal>
        </div>
      </section>
      <section className="section section--tight">
        <div className="container">
          <ol className="timeline">
            {STEPS.map((step, index) => (
              <Reveal as="li" key={step.title} className={`timeline__item tone-${WHO_TONE[step.who]}`} delay={60}>
                <span className="timeline__marker">
                  <Icon name={step.icon} size={20} />
                </span>
                <div className="timeline__card">
                  <div className="timeline__top">
                    <span className="timeline__step">Step {index + 1}</span>
                    <span className="timeline__who">{step.who}</span>
                  </div>
                  <h2>{step.title}</h2>
                  <p>{step.text}</p>
                  <p className="timeline__detail"><Icon name="info" size={14} /> {step.detail}</p>
                </div>
              </Reveal>
            ))}
          </ol>
        </div>
      </section>
      <section className="section section--cta">
        <div className="container">
          <Reveal className="cta-band" variant="zoom">
            <div className="cta-band__glow" aria-hidden="true" />
            <h2>Try it with your own questions.</h2>
            <p>Students can register with their college email; staff and administrators sign in with provisioned accounts.</p>
            <div className="cta-band__actions">
              <a className="button button--light button--lg" href="#/signup">Get Started <Icon name="arrowRight" size={18} /></a>
              <a className="text-link text-link--light" href="#/signin">I already have an account</a>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
