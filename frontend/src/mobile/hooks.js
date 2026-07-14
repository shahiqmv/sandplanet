import { useCallback, useEffect, useRef, useState } from "react";

// Fetch-on-mount with manual reload and a "last updated" stamp. Keeps the
// previously-loaded data visible while refetching (island connections drop —
// stale data beats a blank screen, R6 §10).
export function useAsync(fn, deps = []) {
  const [state, setState] = useState({
    data: null,
    error: null,
    loading: true,
    at: null,
  });
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await fn();
      if (mounted.current)
        setState({ data, error: null, loading: false, at: Date.now() });
    } catch (e) {
      if (mounted.current)
        setState((s) => ({ ...s, error: e, loading: false }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    run();
  }, [run]);

  return { ...state, reload: run };
}
