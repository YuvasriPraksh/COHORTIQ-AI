import type { AnswerStatus, AskResponse, RouteDecision } from "../api/types";

export type VerdictTone = "answered" | "abstained" | "conflict" | "neutral" | "caution";

export interface AnswerVerdict {
  badge: string;
  title: string;
  tone: VerdictTone;
  /** Whether the backend actually returned an answered response with supporting citations. */
  hasCitations: boolean;
}

const VALIDATION_BOILERPLATE =
  "Citation validation failed: no valid supporting citations matched the original retrieved evidence.";

/**
 * Translate a backend citation-validation issue into plain, student-safe language.
 * Raw internal identifiers such as `chunk_id '...'` are never surfaced.
 */
export function sanitizeValidationIssue(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";

  const lower = trimmed.toLowerCase();
  if (lower.includes("supporting text could not be matched")) {
    return "A draft reference could not be matched to the regulation text and was removed.";
  }
  if (lower.includes("unknown chunk_id")) {
    return "A draft reference pointed to an unverified passage and was removed.";
  }
  if (lower.includes("missing chunk_id") || lower.includes("malformed citation")) {
    return "An incomplete draft reference could not be verified and was removed.";
  }
  if (lower.includes("duplicate citation")) {
    return "Duplicate references to the same passage were consolidated.";
  }
  if (lower.includes("due to ") && lower.includes("chunk_id")) {
    return "A draft reference had incomplete source details and was removed.";
  }
  if (lower.includes("no citations provided")) {
    return "No supporting references were provided for this answer.";
  }
  if (lower.includes("no original retrieved evidence")) {
    return "No source passages were available to verify references.";
  }

  // Strip any unexpected `chunk_id '...'` fragments defensively.
  return trimmed
    .replace(/\bfor chunk_id\s+['"][^'"]+['"]/gi, "")
    .replace(/\breferencing unknown chunk_id\s+['"][^'"]+['"]/gi, "referencing an unknown passage")
    .replace(/\bchunk_id\b/gi, "passage reference")
    .replace(/\s{2,}/g, " ")
    .trim();
}

export interface ValidationMessaging {
  /** Remaining explanation from `answer.limitations` after removing duplicated/raw validator text. */
  limitationNote: string | null;
  /** Unique, student-safe validation issue summaries. */
  issues: string[];
  /** Heading for the validation notice when `issues` is non-empty. */
  issuesTitle: string;
}

/**
 * Deduplicate and sanitize `answer.limitations` against `validation_issues` so
 * students see one clear explanation without repeated or internal messages.
 */
export function formatValidationMessaging(
  limitations: string | null,
  validationIssues: string[],
  status: AnswerStatus | string,
): ValidationMessaging {
  const sanitizedIssues: string[] = [];
  const seen = new Set<string>();

  for (const raw of validationIssues) {
    const clean = sanitizeValidationIssue(raw);
    if (clean && !seen.has(clean)) {
      seen.add(clean);
      sanitizedIssues.push(clean);
    }
  }

  let cleanedLimitation = (limitations ?? "").trim();
  if (cleanedLimitation) {
    for (const raw of validationIssues) {
      const target = raw.trim();
      if (target) {
        cleanedLimitation = cleanedLimitation.split(target).join("");
      }
    }
    cleanedLimitation = cleanedLimitation.split(VALIDATION_BOILERPLATE).join("");
    cleanedLimitation = sanitizeValidationIssue(cleanedLimitation);
    if (cleanedLimitation && seen.has(cleanedLimitation)) {
      cleanedLimitation = "";
    }
  }

  const issuesTitle =
    status === "insufficient_evidence" && sanitizedIssues.length > 0
      ? "References could not be verified"
      : "Some citations were removed";

  return {
    limitationNote: cleanedLimitation || null,
    issues: sanitizedIssues,
    issuesTitle,
  };
}

/**
 * Derive an accurate verdict badge, heading, and visual tone from the full
 * backend response without inventing verification claims.
 */
export function resolveAnswerVerdict(response: AskResponse): AnswerVerdict {
  const hasCitations = response.citations.length > 0;
  const routeName: RouteDecision["route"] | undefined = response.route?.route;

  if (routeName === "out_of_scope") {
    return {
      badge: "Outside regulations",
      title: "Outside what I can answer",
      tone: "neutral",
      hasCitations: false,
    };
  }
  if (routeName === "clarify") {
    return {
      badge: "Cohort needed",
      title: "I need your cohort first",
      tone: "neutral",
      hasCitations: false,
    };
  }
  if (response.status === "conflicting_evidence") {
    return {
      badge: "Conflicting regulations",
      title: "The regulations disagree",
      tone: "conflict",
      hasCitations,
    };
  }
  if (response.status === "answered") {
    if (hasCitations) {
      return {
        badge: "Grounded answer",
        title: "Answer",
        tone: "answered",
        hasCitations: true,
      };
    }
    return {
      badge: "No citations attached",
      title: "Answer without citations",
      tone: "caution",
      hasCitations: false,
    };
  }
  return {
    badge: "No grounded answer",
    title: "No grounded answer",
    tone: "abstained",
    hasCitations: false,
  };
}
