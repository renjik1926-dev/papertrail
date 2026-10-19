import { useCallback, useEffect, useState } from "react";

interface AsyncState<T> {
  data: T | null;
  error: string | null;
}

function messageOf(problem: unknown): string {
  return problem instanceof Error ? problem.message : "Something went wrong.";
}

/**
 * Run `load` when it changes (wrap it in useCallback) or when `reload()` is called.
 * State is only set from the promise callbacks, and a stale response is ignored.
 */
export function useAsync<T>(load: () => Promise<T>) {
  const [state, setState] = useState<AsyncState<T>>({ data: null, error: null });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    load().then(
      (data) => {
        if (!cancelled) setState({ data, error: null });
      },
      (problem: unknown) => {
        if (!cancelled) setState((current) => ({ data: current.data, error: messageOf(problem) }));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [load, tick]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  const mutate = useCallback(
    (update: (data: T) => T) =>
      setState((current) =>
        current.data === null ? current : { ...current, data: update(current.data) },
      ),
    [],
  );
  return { ...state, reload, mutate };
}
