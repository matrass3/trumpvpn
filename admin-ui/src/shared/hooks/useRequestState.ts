import { useCallback, useRef, useState } from "react";

export type RequestState<T> = {
  data: T | null;
  pending: boolean;
  error: string;
};

export function useRequestState<T>(loader: () => Promise<T>) {
  const [state, setState] = useState<RequestState<T>>({
    data: null,
    pending: false,
    error: "",
  });
  const inFlightRef = useRef(false);

  const run = useCallback(async () => {
    if (inFlightRef.current) {
      return;
    }
    inFlightRef.current = true;
    setState((prev) => ({ ...prev, pending: true, error: "" }));
    try {
      const data = await loader();
      setState({ data, pending: false, error: "" });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Request failed";
      // Keep the last successful snapshot to avoid dashboard flicker on transient errors.
      setState((prev) => ({ ...prev, pending: false, error: message }));
    } finally {
      inFlightRef.current = false;
    }
  }, [loader]);

  return {
    ...state,
    run,
  };
}

