import { useCallback, useEffect, useState } from 'react';

interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Run an async loader on mount + when deps change; abortable; with reload(). */
export function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    let live = true;
    setLoading(true);
    setError(null);
    fn(ctrl.signal)
      .then((d) => { if (live) { setData(d); setLoading(false); } })
      .catch((e: Error) => {
        if (live && e.name !== 'AbortError') { setError(e.message || 'Error'); setLoading(false); }
      });
    return () => { live = false; ctrl.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}
