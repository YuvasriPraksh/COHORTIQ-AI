import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { useSession } from "../auth/session";

export type Resource<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "error"; data: null; error: string }
  | { status: "ready"; data: T; error: null };

/**
 * Load data from the API with loading, error and retry states. A 401 ends the
 * session. `key` identifies the request; a new key loads again.
 */
export function useResource<T>(key: string, load: (signal: AbortSignal) => Promise<T>) {
  const { handleUnauthorized } = useSession();
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<{ key: string; resource: Resource<T> }>({
    key,
    resource: { status: "loading", data: null, error: null },
  });

  useEffect(() => {
    const controller = new AbortController();
    // Reloading the same key keeps the current data on screen until the new data arrives.
    setState((previous) =>
      previous.key === key && previous.resource.status === "ready"
        ? previous
        : { key, resource: { status: "loading", data: null, error: null } },
    );
    load(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ key, resource: { status: "ready", data, error: null } });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.kind === "unauthorized") {
          handleUnauthorized();
          return;
        }
        const message = error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
        setState({ key, resource: { status: "error", data: null, error: message } });
      });
    return () => controller.abort();
    // `load` is recreated on every render; `key` says when the request really changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, version, handleUnauthorized]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  const resource: Resource<T> =
    state.key === key ? state.resource : { status: "loading", data: null, error: null };
  return { ...resource, reload };
}
