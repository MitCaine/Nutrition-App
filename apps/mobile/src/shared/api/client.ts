import { validateMobileConfig } from "../../../config/runtimeConfig";

const runtimeConfig = validateMobileConfig({
  deploymentMode: process.env.EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE,
  apiUrl: process.env.EXPO_PUBLIC_NUTRITION_API_URL,
  privateAuthToken: process.env.EXPO_PUBLIC_NUTRITION_PRIVATE_AUTH_TOKEN,
});

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

function requestHeaders(input: HeadersInit | undefined): Record<string, string> {
  const result: Record<string, string> = {};
  if (input) {
    if (Array.isArray(input)) {
      for (const [name, value] of input) result[name] = value;
    } else if (typeof Headers !== "undefined" && input instanceof Headers) {
      input.forEach((value, name) => { result[name] = value; });
    } else {
      Object.assign(result, input);
    }
  }
  return result;
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = requestHeaders(options.headers);
  if (!Object.keys(headers).some((name) => name.toLowerCase() === "content-type")) {
    headers["Content-Type"] = "application/json";
  }
  if (runtimeConfig.privateAuthToken) {
    for (const name of Object.keys(headers)) {
      if (name.toLowerCase() === "authorization") delete headers[name];
    }
    headers.Authorization = `Bearer ${runtimeConfig.privateAuthToken}`;
  }
  const response = await fetch(`${runtimeConfig.apiBaseUrl}${path}`, {
    ...options,
    headers,
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
