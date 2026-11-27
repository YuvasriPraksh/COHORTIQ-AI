import { useEffect, useRef, useState } from "react";

import { getRegulationPages } from "../api/cohortiq";
import type { DocumentPage } from "../api/types";
import { useResource } from "../hooks/useResource";
import { EmptyState, Loaded } from "./ui";

/** Split `text` around the cited excerpt, ignoring differences in whitespace and case. */
export function findExcerpt(text: string, excerpt: string | null | undefined): [string, string, string] | null {
  const words = (excerpt ?? "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return null;
  const pattern = words.map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+");
  const match = new RegExp(pattern, "i").exec(text);
  if (!match) return null;
  return [text.slice(0, match.index), match[0], text.slice(match.index + match[0].length)];
}

function PageViewer({ pages, initialPage, excerpt }: { pages: DocumentPage[]; initialPage?: number; excerpt?: string | null }) {
  const [number, setNumber] = useState(initialPage ?? pages[0]?.page_number ?? 1);
  const index = Math.max(0, pages.findIndex((page) => page.page_number === number));
  const page = pages[index];
  const markRef = useRef<HTMLElement>(null);

  useEffect(() => {
    markRef.current?.scrollIntoView?.({ block: "center" });
  }, [number]);

  if (!page) return <EmptyState title="No pages were extracted from this document." />;
  const text = page.extracted_text ?? "";
  const parts = page.page_number === initialPage ? findExcerpt(text, excerpt) : null;

  return (
    <div className="viewer">
      <div className="viewer__bar">
        <button
          type="button"
          className="button button--ghost button--compact"
          disabled={index === 0}
          onClick={() => setNumber(pages[index - 1]!.page_number)}
        >
          Previous page
        </button>
        <label className="viewer__select">
          <span>Page</span>
          <select value={page.page_number} onChange={(event) => setNumber(Number(event.target.value))}>
            {pages.map((item) => (
              <option key={item.page_number} value={item.page_number}>
                {item.page_number}
                {item.extraction_status && item.extraction_status !== "success" ? " (no text)" : ""}
              </option>
            ))}
          </select>
          <span>of {pages.length}</span>
        </label>
        <button
          type="button"
          className="button button--ghost button--compact"
          disabled={index === pages.length - 1}
          onClick={() => setNumber(pages[index + 1]!.page_number)}
        >
          Next page
        </button>
      </div>
      {text.trim() ? (
        <pre className="viewer__text" tabIndex={0} aria-label={`Extracted text of page ${page.page_number}`}>
          {parts ? (
            <>
              {parts[0]}
              <mark ref={markRef}>{parts[1]}</mark>
              {parts[2]}
            </>
          ) : (
            text
          )}
        </pre>
      ) : (
        <EmptyState title="No text could be extracted from this page.">
          It may be a scanned image that needs OCR or manual inspection.
        </EmptyState>
      )}
    </div>
  );
}

/** The extracted text of one regulation, page by page. */
export function RegulationPages({
  token,
  regulationId,
  initialPage,
  excerpt,
}: {
  token: string;
  regulationId: number;
  initialPage?: number;
  excerpt?: string | null;
}) {
  const pages = useResource(`pages:${regulationId}`, (signal) => getRegulationPages(token, regulationId, signal));
  return (
    <Loaded resource={pages}>
      {(data) => <PageViewer pages={data} initialPage={initialPage} excerpt={excerpt} />}
    </Loaded>
  );
}

export interface SourceTarget {
  regulationId: number;
  page: number;
  title: string;
  excerpt: string | null;
}

/** A dialog showing a cited page without leaving the answer. */
export function SourceDialog({ token, source, onClose }: { token: string; source: SourceTarget; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    return () => opener?.focus?.();
  }, []);

  return (
    <div
      className="overlay"
      onClick={(event) => event.target === event.currentTarget && onClose()}
      onKeyDown={(event) => event.key === "Escape" && onClose()}
    >
      <div className="dialog panel" role="dialog" aria-modal="true" aria-labelledby="source-title">
        <div className="card__head">
          <h2 id="source-title" className="card__title">
            {source.title}
          </h2>
          <button ref={closeRef} type="button" className="button button--ghost button--compact" onClick={onClose}>
            Close
          </button>
        </div>
        <RegulationPages
          token={token}
          regulationId={source.regulationId}
          initialPage={source.page}
          excerpt={source.excerpt}
        />
      </div>
    </div>
  );
}
