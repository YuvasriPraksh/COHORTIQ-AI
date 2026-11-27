import type { Citation, RetrievalResult } from "../api/types";

function formatDocumentName(document: string | null): string {
  return document?.trim() || "Approved regulation";
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
          <li
            key={`${citation.document_name ?? "doc"}-${citation.page_number ?? "p"}-${index}`}
            className="citation"
            style={{ animationDelay: `${index * 70}ms` }}
          >
            <div className="citation__source">
              <span className="citation__number" aria-hidden="true">
                {index + 1}
              </span>
              <div className="citation__meta">
                <span className="citation__doc">{formatDocumentName(citation.document_name)}</span>
                {citation.regulation_version ? (
                  <span className="citation__tag">v{citation.regulation_version}</span>
                ) : null}
                {citation.page_number != null ? (
                  <span className="citation__tag citation__tag--page">Page {citation.page_number}</span>
                ) : null}
              </div>
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

/** Which regulation pages were searched (metadata only; no raw relevance scores or chunk IDs). */
export function SourcesSearched({ results }: { results: RetrievalResult[] }) {
  if (!results.length) return null;
  return (
    <details className="sources">
      <summary>
        <span>
          Passages searched <span className="count">{results.length}</span>
        </span>
        <span className="sources__chevron" aria-hidden="true" />
      </summary>
      <ul>
        {results.map((result, index) => (
          <li key={`${result.regulation_id ?? "r"}-${result.page_number ?? "p"}-${index}`}>
            <span className="sources__doc">
              {formatDocumentName(result.document_name)}
              {result.regulation_version ? ` · version ${result.regulation_version}` : ""}
            </span>
            <span className="sources__meta">
              {result.page_number != null ? `Page ${result.page_number}` : "Page unknown"}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}
