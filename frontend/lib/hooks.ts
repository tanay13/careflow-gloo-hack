"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Fetch a resource and keep it fresh by polling. `fastWhile` speeds polling up (e.g. while the agent runs). */
export function usePoll<T>(path: string | null, intervalMs = 4000, fastWhile?: (d: T) => boolean) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fastRef = useRef(fastWhile);
  fastRef.current = fastWhile;

  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api.get<T>(path);
      setData(d);
      setError(null);
      return d;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const d = await load();
      if (!alive) return;
      const fast = d && fastRef.current ? fastRef.current(d) : false;
      timer.current = setTimeout(tick, fast ? 350 : intervalMs);
    };
    tick();
    return () => {
      alive = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load, intervalMs]);

  return { data, error, loading, reload: load };
}
