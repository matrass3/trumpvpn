import { useCallback, useState } from "react";

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

  const run = useCallback(async () => {
    setState((prev) => ({ ...prev, pending: true, error: "" }));
    try {
      const data = await loader();
      setState({ data, pending: false, error: "" });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Request failed";
      setState({ data: null, pending: false, error: message });
    }
  }, [loader]);

  return {
    ...state,
    run,
  };
}
