import type { AgentResultResponse, ApiErrorBody, ChatResponse, LoginResponse, MeResponse } from "./types";

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

export function sendChatMessage(message: string): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", { method: "POST", body: JSON.stringify({ message }) });
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
