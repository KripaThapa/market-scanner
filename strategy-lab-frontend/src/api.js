export async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData))
    headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    ...options,
    headers,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    const error = new Error(
      typeof detail === "string"
        ? detail
        : detail?.message || `Request failed (${response.status})`,
    );
    error.details = typeof detail === "object" ? detail : null;
    throw error;
  }
  return body;
}
