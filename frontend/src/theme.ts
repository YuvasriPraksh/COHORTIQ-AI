import { useEffect, useState } from "react";

/** Light/dark theme: stored per browser, applied as `data-theme` on <html>. */
export type Theme = "light" | "dark";

const STORAGE_KEY = "cohortiq.theme";
const listeners = new Set<(theme: Theme) => void>();

function readInitialTheme(): Theme {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // Storage can be unavailable (privacy modes); fall back to the OS preference.
  }
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

let current: Theme = typeof window === "undefined" ? "dark" : readInitialTheme();

/** Apply the saved theme before React renders, so the page never flashes the wrong theme. */
export function applyInitialTheme(): void {
  document.documentElement.dataset.theme = current;
}

export function setTheme(next: Theme): void {
  current = next;
  document.documentElement.dataset.theme = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // The theme still applies for this page even if it cannot be saved.
  }
  listeners.forEach((listener) => listener(next));
}

export function useTheme(): [Theme, () => void] {
  const [theme, setLocal] = useState<Theme>(current);
  useEffect(() => {
    listeners.add(setLocal);
    setLocal(current);
    return () => {
      listeners.delete(setLocal);
    };
  }, []);
  return [theme, () => setTheme(current === "dark" ? "light" : "dark")];
}
