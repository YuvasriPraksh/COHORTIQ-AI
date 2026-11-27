import type { Citation, RetrievalResult } from "../api/types";

function sourceName(document: string | null, version: string | null): string {
  const name = document?.trim() || "Regulation";
  return version ? `${name} · version ${version}` : name;
}

/** Citations validated by the backend against the retrieved evidence. */
export function Citations({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;
  return (
    <section className="evidence" aria-labelledby="citations-heading">
      <h3 id="citations-heading" className="evidence__heading">
        Evidence <span className="count">{citations.length}</span>
      </h3>
      <ol className="citations">
        {citations.map((citation, index) => (
          <li key={`${citation.chunk_id ?? "c"}-${index}`} className="citation" style={{ animationDelay: `${index * 70}ms` }}>
            <div className="citation__source">
              <span className="citation__number" aria-hidden="true">
                {index + 1}
              </span>
              <span>
                {sourceName(citation.document_name, citation.regulation_version)}
                {citation.page_number != null ? <span className="citation__page"> · page {citation.page_number}</span> : null}
              </span>
            </div>
            {citation.relevant_supporting_text ? (
              <blockquote className="citation__quote">{citation.relevant_supporting_text}</blockquote>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Which regulation pages were searched (metadata only; the API never returns chunk text here). */
export function SourcesSearched({ results }: { results: RetrievalResult[] }) {
  if (!results.length) return null;
  return (
    <details className="sources">
      <summary>
        Passages searched <span className="count">{results.length}</span>
      </summary>
      <ul>
        {results.map((result, index) => (
          <li key={`${result.chunk_id ?? "r"}-${index}`}>
            <span>{sourceName(result.document_name, result.regulation_version)}</span>
            <span className="sources__meta">
              {result.page_number != null ? `page ${result.page_number}` : "page unknown"}
              {result.retrieval_score != null ? ` · match ${result.retrieval_score.toFixed(1)}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}
