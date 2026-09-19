import { useCallback, useEffect, useRef, useState } from "react";

export async function request(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    const error = new Error(
      typeof detail === "string"
        ? detail
        : detail?.message ||
            `Request failed (${response.status}). Please try again.`,
    );
    error.report = detail?.report;
    throw error;
  }
  if (!body) throw new Error("The API returned an invalid response.");
  return body;
}

export function useDashboard() {
  const [data, setData] = useState(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true);
  const controller = useRef(null);
  const refresh = useCallback(async () => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    const timeout = setTimeout(() => current.abort("timeout"), 20000);
    try {
      const body = await request("/api/dashboard", { signal: current.signal });
      if (controller.current === current) {
        setData(body);
        setError("");
      }
    } catch (err) {
      if (
        controller.current === current &&
        (!current.signal.aborted || current.signal.reason === "timeout")
      )
        setError(
          "Cannot refresh scanner data. Check that the backend is running. Showing the last available results.",
        );
    } finally {
      clearTimeout(timeout);
      if (controller.current === current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 15000);
    return () => {
      clearInterval(timer);
      controller.current?.abort();
    };
  }, [refresh]);
  return { data, error, loading, refresh };
}
