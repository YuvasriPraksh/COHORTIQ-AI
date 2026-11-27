import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import type { AskResponse, Cohort } from "../api/types";

export interface HistoryEntry {
  id: number;
  question: string;
  cohort: Cohort;
  response: AskResponse;
  askedAt: Date;
}

/**
 * Questions answered during this sign-in. The API stores no question history,
 * so this lives in memory only and is cleared on sign-out, 401, or page reload.
 */
interface History {
  entries: HistoryEntry[];
  /** The answer to show when the Ask page opens, if any. */
  activeId: number | null;
  add: (question: string, cohort: Cohort, response: AskResponse) => void;
  select: (id: number | null) => void;
  clear: () => void;
  /** A question typed elsewhere (for example a suggestion on the home page). */
  draft: string;
  setDraft: (text: string) => void;
}

const HistoryContext = createContext<History | null>(null);
const LIMIT = 15;

export function HistoryProvider({ children }: { children: ReactNode }) {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const nextId = useRef(1);

  const add = useCallback((question: string, cohort: Cohort, response: AskResponse) => {
    const id = nextId.current++;
    setEntries((list) => [{ id, question, cohort, response, askedAt: new Date() }, ...list].slice(0, LIMIT));
    setActiveId(id);
  }, []);

  const clear = useCallback(() => {
    setEntries([]);
    setActiveId(null);
    setDraft("");
  }, []);

  const value = useMemo(
    () => ({ entries, activeId, add, select: setActiveId, clear, draft, setDraft }),
    [entries, activeId, add, clear, draft],
  );
  return <HistoryContext.Provider value={value}>{children}</HistoryContext.Provider>;
}

export function useHistory(): History {
  const value = useContext(HistoryContext);
  if (!value) throw new Error("useHistory must be used inside HistoryProvider.");
  return value;
}
