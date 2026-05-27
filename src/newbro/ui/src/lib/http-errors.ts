function extractMessageFromObject(value: Record<string, unknown>): string | null {
  const detail = value.detail;
  if (typeof detail === "string" && detail.trim()) {
    return formatHttpErrorBody(detail);
  }
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const nested = extractMessageFromObject(detail as Record<string, unknown>);
    if (nested) return nested;
  }
  const reason = value.reason;
  if (typeof reason === "string" && reason.trim()) {
    return reason.trim();
  }
  const message = value.message;
  if (typeof message === "string" && message.trim()) {
    return message.trim();
  }
  return null;
}

export function formatHttpErrorBody(body: string): string {
  const text = body.trim();
  if (!text) return "";
  try {
    const parsed = JSON.parse(text) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const message = extractMessageFromObject(parsed as Record<string, unknown>);
      if (message) return message;
      return "";
    }
  } catch {}
  return text;
}

export async function ensureOk(response: Response): Promise<Response> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(formatHttpErrorBody(text) || `Request failed with status ${response.status}`);
  }
  return response;
}
