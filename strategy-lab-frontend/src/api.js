export async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
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
