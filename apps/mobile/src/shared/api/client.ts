const API_BASE_URL = "http://localhost:8000/api/v1";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor({ status, body, message }: { status: number; body: unknown; message: string }) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
  });

  if (!response.ok) {
    const rawBody = await response.text();
    const parsedBody = parseResponseBody(rawBody);
    throw new ApiError({
      status: response.status,
      body: parsedBody,
      message: errorMessage(response.status, parsedBody, rawBody),
    });
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

function parseResponseBody(rawBody: string): unknown {
  if (!rawBody) {
    return null;
  }
  try {
    return JSON.parse(rawBody) as unknown;
  } catch {
    return rawBody;
  }
}

function errorMessage(status: number, body: unknown, rawBody: string): string {
  const detail = typeof body === "object" && body !== null && "detail" in body ? (body as { detail?: unknown }).detail : null;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    const firstMessage = detail
      .map((item) => (typeof item === "object" && item !== null && "msg" in item ? String(item.msg) : ""))
      .find(Boolean);
    if (firstMessage) {
      return firstMessage;
    }
  }
  if (typeof body === "string" && body.trim()) {
    return body;
  }
  return rawBody || `Request failed with status ${status}`;
}
