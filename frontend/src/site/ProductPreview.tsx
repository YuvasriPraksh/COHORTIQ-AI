import { Icon, LogoMark } from "../components/icons";

/**
 * Hero product preview. The question, answer and citation mirror a real answer
 * CohortIQ produced from the R2023 B.Tech regulations (page 15) during testing.
 */
export function ProductPreview() {
  return (
    <figure className="preview" aria-label="Example of a CohortIQ answer with its citation">
      <div className="preview__glow" aria-hidden="true" />
      <div className="preview__window">
        <div className="preview__bar">
          <span className="preview__dots" aria-hidden="true"><i /><i /><i /></span>
          <span className="preview__url">cohortiq · Ask</span>
          <span className="preview__cohort"><Icon name="graduation" size={14} /> Batch 2024 · B.Tech CSE</span>
        </div>
        <div className="preview__body">
          <aside className="preview__rail" aria-hidden="true">
            <LogoMark size={26} />
            <span className="is-active"><Icon name="message" size={16} /></span>
            <span><Icon name="book" size={16} /></span>
            <span><Icon name="bell" size={16} /></span>
          </aside>
          <div className="preview__chat">
            <p className="preview__q">How many marks are awarded for attendance in theory courses?</p>
            <div className="preview__a">
              <div className="preview__a-head">
                <span className="preview__ai"><Icon name="sparkles" size={14} /> CohortIQ</span>
                <span className="pill pill--good"><Icon name="checkCircle" size={13} /> Grounded answer</span>
              </div>
              <p>
                Theory courses award <mark>5 marks for attendance</mark>. Attendance of <mark>95% and above</mark> earns the full 5 marks.
                <sup className="preview__ref">1</sup>
              </p>
              <div className="preview__cite">
                <span className="preview__cite-icon"><Icon name="file" size={16} /></span>
                <div>
                  <strong>B.Tech Academic Regulations · R2023</strong>
                  <span>“5 marks for 95% and above · 4 marks for 90% and above…”</span>
                </div>
                <span className="preview__page">Page 15</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="preview__float preview__float--a" aria-hidden="true">
        <Icon name="shield" size={16} /> Approved regulations only
      </div>
      <div className="preview__float preview__float--b" aria-hidden="true">
        <Icon name="target" size={16} /> Matched to your cohort
      </div>
      <figcaption className="preview__caption">Example based on a real answer from the R2023 regulations.</figcaption>
    </figure>
  );
}
