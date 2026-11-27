import { useEffect, useState } from "react";

/**
 * Minimal hash router (no extra dependency). Paths look like "#/regulations/3".
 * Which pages a role may see is decided in App; the API enforces permissions.
 */
function currentPath(): string {
  return window.location.hash.replace(/^#/, "") || "/";
}

export function useHashPath(): string {
  const [path, setPath] = useState(currentPath);
  useEffect(() => {
    const update = () => setPath(currentPath());
    window.addEventListener("hashchange", update);
    update();
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return path;
}

export function navigate(path: string): void {
  window.location.hash = path;
}

export function clearPath(): void {
  if (window.location.hash) {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }
}
