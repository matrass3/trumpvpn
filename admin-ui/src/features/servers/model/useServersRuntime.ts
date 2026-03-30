import { useCallback, useEffect } from "react";
import { ApiError } from "../../../shared/api/httpClient";
import { useRequestState } from "../../../shared/hooks/useRequestState";
import { getServersRuntime, type ServersRuntimeSnapshot } from "../api/serversApi";

type UseServersRuntimeOptions = {
  onUnauthorized?: () => void;
};

export function useServersRuntime(options: UseServersRuntimeOptions = {}) {
  const { data, pending, error, run } = useRequestState<ServersRuntimeSnapshot>(async () => {
    try {
      return await getServersRuntime();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        options.onUnauthorized?.();
      }
      throw e;
    }
  });

  const refresh = useCallback(() => {
    void run();
  }, [run]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return {
    snapshot: data,
    pending,
    error,
    refresh,
  };
}
