import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api";

export interface ApiState<T> {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  reload: () => void;
}

export function useApi<T>(path: string | null): ApiState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<ApiError>();
  const [loading, setLoading] = useState(path !== null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (path === null) return;
    let active = true;
    setLoading(true);
    api<T>(path)
      .then((d) => {
        if (active) {
          setData(d);
          setError(undefined);
        }
      })
      .catch((e: unknown) => {
        if (active) setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [path, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}
