import { fetchHealth } from "../api/cohortiq";
import { useResource } from "../hooks/useResource";
import { navigate } from "../nav/router";
import { Badge, Card, Loaded, PageHeader, type Tone } from "./ui";

interface ModuleStatus {
  id: string;
  name: string;
  pptScope: string;
  frontend: string;
  endpoint: string;
  data: string;
  status: "Working" | "Partial" | "Offline only";
  tone: Tone;
  implemented: string;
  gap: string;
  action?: { label: string; path: string };
}

const MODULES: ModuleStatus[] = [
  {
    id: "M1",
    name: "LLM Integration",
    pptScope: "Gemini API, prompt templates, JSON output validated with Pydantic",
    frontend: "Ask page",
    endpoint: "POST /api/v1/query/ask",
    data: "Applicable approved-regulation chunks; Gemini is called only after evidence retrieval.",
    status: "Working",
    tone: "good",
    implemented: "Gemini structured JSON generation, Pydantic GroundedAnswer validation, and strict citation verification against source chunks.",
    gap: "All core prototype behavior is active in Ask.",
    action: { label: "Open Ask", path: "/" },
  },
  {
    id: "M2",
    name: "Conversation History",
    pptScope: "Saved sessions, cohort memory, summary of older turns",
    frontend: "Ask page history rail",
    endpoint: "No conversation-history endpoint",
    data: "Current browser session only; cleared on sign-out or session expiry.",
    status: "Partial",
    tone: "caution",
    implemented: "In-session question & answer history rail in the React workspace (cleared automatically on sign-out or 401).",
    gap: "Server-side saved sessions, multi-turn query context, and summarization of older turns are not implemented in the backend.",
    action: { label: "Open Ask", path: "/" },
  },
  {
    id: "M3",
    name: "Document Processing",
    pptScope: "PyMuPDF; fixed, recursive and semantic chunking compared",
    frontend: "Regulations page; admin upload and review",
    endpoint: "GET /api/v1/regulations; POST /api/v1/regulations/ingest; GET /api/v1/regulations/{id}/pages",
    data: "SQLite regulation metadata, extracted pages, and chunks.",
    status: "Working",
    tone: "good",
    implemented: "PyMuPDF page extraction, SQLite page storage, fixed_size/recursive/semantic chunking selectable per query, and page reader.",
    gap: "Admin PDF ingestion and approval are available to administrator accounts.",
    action: { label: "Open Regulations", path: "/regulations" },
  },
  {
    id: "M4",
    name: "Query Processing",
    pptScope: "Query rewriting, reference resolution, multi-query",
    frontend: "Ask page",
    endpoint: "POST /api/v1/query/ask",
    data: "Submitted question and deterministic clause-reference detection.",
    status: "Partial",
    tone: "caution",
    implemented: "Deterministic clause/section reference detection (e.g. Clause 10.1) and academic tokenization.",
    gap: "LLM query rewriting, pronoun reference resolution, and multi-query expansion are not implemented.",
    action: { label: "Try Clause Lookup", path: "/" },
  },
  {
    id: "M5",
    name: "Retrieval Engineering",
    pptScope: "pgvector + BM25, RRF fusion, cross-encoder rerank, cohort filter",
    frontend: "Ask page and cohort regulation view",
    endpoint: "POST /api/v1/query/ask; GET /api/v1/cohorts/{admission_batch}/{programme}/regulations",
    data: "Approved SQLite regulation chunks filtered by exact batch and programme, ranked with BM25.",
    status: "Partial",
    tone: "caution",
    implemented: "Deterministic cohort-applicability and approved-only filtering with rank-bm25 retrieval over SQLite chunks.",
    gap: "PostgreSQL/pgvector semantic search, RRF hybrid fusion, and cross-encoder reranking are planned.",
    action: { label: "View Cohort Rules", path: "/regulations" },
  },
  {
    id: "M6",
    name: "Adaptive RAG",
    pptScope: "Router: answer, ask, compare, conflict or abstain",
    frontend: "Ask page",
    endpoint: "POST /api/v1/query/ask",
    data: "Router handles general, clause_lookup, out_of_scope, clarify, and low_evidence routes.",
    status: "Partial",
    tone: "caution",
    implemented: "Deterministic pre-generation routing for general questions, clause lookup, out-of-scope questions, clarification, and low evidence.",
    gap: "Compare and conflicting-evidence routes are not implemented; insufficient evidence abstains.",
    action: { label: "Test Router in Ask", path: "/" },
  },
  {
    id: "M7",
    name: "Evaluation",
    pptScope: "100-question dataset, 4 configurations, Ragas + own metrics",
    frontend: "Modules page reports the offline harness",
    endpoint: "No evaluation API endpoint",
    data: "Offline evaluation datasets and CLI reports under evaluation/.",
    status: "Offline only",
    tone: "neutral",
    implemented: "Offline CLI harness (evaluation/) with retrieval_v1 (20 cases) & routing_v1 (40 cases) measuring Precision@5, Recall@5, MRR, Wrong-Version Rate, and Abstention Accuracy.",
    gap: "100-question dataset, Ragas metrics, and live evaluation UI endpoint are not exposed by the API.",
  },
  {
    id: "M8",
    name: "Backend & Reliability",
    pptScope: "FastAPI, SSE, cache, rate limit, retries, injection tests, logs",
    frontend: "Modules page health status; admin audit page",
    endpoint: "GET /api/v1/health; GET /api/v1/admin/audit-events",
    data: "FastAPI service health and persisted audit events; no SSE, response cache, API rate limit, or automatic job retries.",
    status: "Partial",
    tone: "caution",
    implemented: "FastAPI REST API, Argon2id + JWT auth, RBAC, upload/body limits, append-only audit log, prompt-injection tests, and client timeout/cancel.",
    gap: "SSE token streaming, response cache, API rate limiting, and automatic job retries are not implemented.",
  },
];

export function ModulesPage({ isAdmin }: { isAdmin: boolean }) {
  const health = useResource("health", (signal) => fetchHealth(signal));

  return (
    <div className="stack">
      <PageHeader
        title="Eight CohortIQ modules"
        subtitle="Honest mapping between the CohortIQ evaluation architecture and verified live capabilities."
      />

      <Card
        title="Backend connection"
        actions={
          <button type="button" className="button button--ghost button--compact" onClick={health.reload}>
            Check health
          </button>
        }
      >
        <Loaded resource={health}>
          {(data) => (
            <div className="health-row">
              <Badge tone={data.status === "ok" ? "good" : "caution"}>API {data.status}</Badge>
              <span>Connected to FastAPI backend ({`/api/v1/health`}).</span>
            </div>
          )}
        </Loaded>
      </Card>

      <div className="module-grid">
        {MODULES.map((mod) => (
          <article key={mod.id} className="panel card module-card">
            <div className="card__head">
              <h2 className="card__title">
                {mod.id} · {mod.name}
              </h2>
              <Badge tone={mod.tone}>{mod.status}</Badge>
            </div>
            <p className="module-card__scope">{mod.pptScope}</p>
            <p className="module-card__detail">
              <strong>UI:</strong> {mod.frontend}
            </p>
            <p className="module-card__detail">
              <strong>API:</strong> {mod.endpoint}
            </p>
            <p className="module-card__detail">
              <strong>Data:</strong> {mod.data}
            </p>
            <p className="module-card__detail">
              <strong>Implemented:</strong> {mod.implemented}
            </p>
            <p className="module-card__detail muted">
              <strong>Scope boundary:</strong> {mod.gap}
            </p>
            <div className="module-card__foot">
              {mod.action ? (
                <button
                  type="button"
                  className="button button--ghost button--compact"
                  onClick={() => navigate(mod.action!.path)}
                >
                  {mod.action.label}
                </button>
              ) : null}
              {mod.id === "M8" && isAdmin ? (
                <button
                  type="button"
                  className="button button--ghost button--compact"
                  onClick={() => navigate("/admin/audit")}
                >
                  Open Audit Log
                </button>
              ) : null}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
