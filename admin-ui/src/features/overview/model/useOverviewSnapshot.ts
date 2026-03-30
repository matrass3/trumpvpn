import { useCallback, useEffect } from "react";
import { ApiError } from "../../../shared/api/httpClient";
import { useRequestState } from "../../../shared/hooks/useRequestState";
import { getOverviewSnapshot, type OverviewSnapshot } from "../api/overviewApi";

type UseOverviewSnapshotOptions = {
  onUnauthorized?: () => void;
};

export function useOverviewSnapshot(options: UseOverviewSnapshotOptions = {}) {
  const { data, pending, error, run } = useRequestState<OverviewSnapshot>(async () => {
    try {
      return await getOverviewSnapshot();
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
