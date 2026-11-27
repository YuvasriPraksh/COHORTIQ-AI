import type { Citation, RetrievalResult } from "../api/types";
import type { SourceTarget } from "./PageText";

function formatDocumentName(document: string | null): string {
  return document?.trim() || "Approved regulation";
}

/** Where a retrieved passage can be read in full, if the API identified it. */
function sourceFor(result: RetrievalResult | undefined, excerpt: string | null): SourceTarget | null {
  const regulationId = Number(result?.regulation_id);
  if (!result || !Number.isInteger(regulationId) || regulationId <= 0 || result.page_number == null) return null;
  return {
    regulationId,
    page: result.page_number,
    title: `${formatDocumentName(result.document_name)} · page ${result.page_number}`,
    excerpt,
  };
}

type OpenSource = (source: SourceTarget) => void;

/** Citations validated by the backend against the retrieved evidence. */
export function Citations({
  citations,
  results = [],
  onOpenSource,
}: {
  citations: Citation[];
  results?: RetrievalResult[];
  onOpenSource?: OpenSource;
}) {
  if (!citations.length) return null;
  return (
    <section className="evidence" aria-labelledby="citations-heading">
      <h3 id="citations-heading" className="evidence__heading">
        Evidence <span className="count">{citations.length}</span>
      </h3>
      <ol className="citations">
        {citations.map((citation, index) => {
          const source = sourceFor(
            results.find((result) => String(result.chunk_id) === citation.chunk_id),
            citation.relevant_supporting_text,
          );
          return (
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
              {source && onOpenSource ? (
                <button type="button" className="link-button citation__open" onClick={() => onOpenSource(source)}>
                  Read the full page
                </button>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** Which regulation pages were searched (metadata only; no raw relevance scores or chunk IDs). */
export function SourcesSearched({
  results,
  onOpenSource,
}: {
  results: RetrievalResult[];
  onOpenSource?: OpenSource;
}) {
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
        {results.map((result, index) => {
          const source = sourceFor(result, null);
          return (
            <li key={`${result.regulation_id ?? "r"}-${result.page_number ?? "p"}-${index}`}>
              <span className="sources__doc">
                {formatDocumentName(result.document_name)}
                {result.regulation_version ? ` · version ${result.regulation_version}` : ""}
              </span>
              <span className="sources__meta">
                {result.page_number != null ? `Page ${result.page_number}` : "Page unknown"}
                {source && onOpenSource ? (
                  <button
                    type="button"
                    className="link-button sources__open"
                    aria-label={`View page ${result.page_number} of ${formatDocumentName(result.document_name)}`}
                    onClick={() => onOpenSource(source)}
                  >
                    View
                  </button>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
    </details>
  );
}
