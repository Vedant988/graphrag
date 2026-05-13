export async function parseApiResponse(response: Response): Promise<any> {
  const contentType = response.headers.get("content-type") || "";

  if (contentType.includes("application/json")) {
    return response.json();
  }

  const text = await response.text();
  const trimmed = text.trim();

  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      return JSON.parse(trimmed);
    } catch {
      // fall through to a structured non-JSON error payload
    }
  }

  return {
    detail:
      response.status >= 500
        ? `Server error (${response.status}). Please try again later.`
        : trimmed || `Request failed with status ${response.status}.`,
    rawText: text,
  };
}
