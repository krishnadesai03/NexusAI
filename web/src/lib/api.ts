import type { AgentResultResponse, ApiErrorBody, ChatResponse, LoginResponse, MeResponse, TraceEvent } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_STORAGE_KEY = "enterprise-ai-token";

export class ApiError extends Error {
  status: number;
  agent?: string;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error);
    this.status = status;
    this.agent = body.agent;
  }
}

// Guarded for the (unlikely, but cheap-to-guard) case this module is ever evaluated during
// server rendering rather than only from Client Components' event handlers/effects.
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
}

async function request<T>(path: string, options: RequestInit = {}, auth = true): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (auth) {
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });

  if (response.status === 204) return undefined as T;

  const body = await response.json();
  if (!response.ok) {
    throw new ApiError(response.status, body as ApiErrorBody);
  }
  return body as T;
}

export function login(email: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }, false);
}

export function me(): Promise<MeResponse> {
  return request<MeResponse>("/auth/me", { method: "GET" });
}

export function logout(): Promise<void> {
  return request<void>("/auth/logout", { method: "POST" });
}

/**
 * /chat streams Server-Sent Events (api/chat.py) rather than returning one JSON response — this
 * powers the live "Working" trace panel. Uses fetch()+a manual ReadableStream reader instead of
 * the browser's native EventSource specifically because EventSource can't send a custom
 * Authorization header, and putting the session token in the URL as a query param instead would
 * violate the same "never put sensitive data in a URL" rule this project already follows
 * everywhere else.
 *
 * `onEvent` receives every event (including `done`/`error`) as it arrives — the trace panel
 * renders directly off that stream. This function additionally resolves with the final
 * ChatResponse (from the `done` event) or throws (on an `error` event), so callers who only want
 * the final answer don't have to duplicate that extraction logic themselves.
 */
export async function streamChatMessage(message: string, onEvent: (event: TraceEvent) => void): Promise<ChatResponse> {
  const headers = new Headers();
  headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message }),
  });

  if (!response.ok) {
    const body = await response.json();
    throw new ApiError(response.status, body as ApiErrorBody);
  }
  if (!response.body) {
    throw new Error("Streaming response has no body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: ChatResponse | null = null;
  let streamError: string | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);
      if (!rawEvent.startsWith("data:")) continue;

      const event = JSON.parse(rawEvent.slice("data:".length).trim()) as TraceEvent;
      onEvent(event);
      if (event.type === "done") finalResult = event.result;
      if (event.type === "error") streamError = event.error;
    }
  }

  if (streamError) throw new Error(streamError);
  if (finalResult) return finalResult;
  throw new Error("Stream ended without a result.");
}

export function confirmPending(agent: string): Promise<AgentResultResponse> {
  return request<AgentResultResponse>("/pending/confirm", { method: "POST", body: JSON.stringify({ agent }) });
}

export function cancelPending(agent: string): Promise<AgentResultResponse> {
  return request<AgentResultResponse>("/pending/cancel", { method: "POST", body: JSON.stringify({ agent }) });
}

export function revisePending(agent: string, editInstructions: string): Promise<AgentResultResponse> {
  return request<AgentResultResponse>("/pending/revise", {
    method: "POST",
    body: JSON.stringify({ agent, edit_instructions: editInstructions }),
  });
}
