import type {
  AgentResultResponse,
  ApiErrorBody,
  ChatResponse,
  ConversationDetail,
  ConversationSummary,
  DemoDelivery,
  DemoPersona,
  DemoSessionResponse,
  LoginResponse,
  MeResponse,
  TraceEvent,
} from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const ACCESS_TOKEN_KEY = "enterprise-ai-access-token";
const REFRESH_TOKEN_KEY = "enterprise-ai-refresh-token";
const DEMO_SESSIONS_KEY = "enterprise-ai-demo-sessions";

export class ApiError extends Error {
  status: number;
  agent?: string;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error);
    this.status = status;
    this.agent = body.agent;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACCESS_TOKEN_KEY);
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setSession(session: LoginResponse): void {
  window.localStorage.setItem(ACCESS_TOKEN_KEY, session.token);
  window.localStorage.setItem(REFRESH_TOKEN_KEY, session.refresh_token);
}

export function clearSession(): void {
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
}

function getSavedDemoSessions(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(window.localStorage.getItem(DEMO_SESSIONS_KEY) ?? "{}") as Record<string, string>;
  } catch {
    window.localStorage.removeItem(DEMO_SESSIONS_KEY);
    return {};
  }
}

function saveDemoToken(personaSlug: string, token: string): void {
  const sessions = getSavedDemoSessions();
  sessions[personaSlug] = token;
  window.localStorage.setItem(DEMO_SESSIONS_KEY, JSON.stringify(sessions));
}

function removeDemoToken(personaSlug: string): void {
  const sessions = getSavedDemoSessions();
  delete sessions[personaSlug];
  window.localStorage.setItem(DEMO_SESSIONS_KEY, JSON.stringify(sessions));
}

function activateDemoToken(token: string): void {
  window.localStorage.setItem(ACCESS_TOKEN_KEY, token);
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
}

function isDemoToken(token: string | null): boolean {
  return Boolean(token?.startsWith("demo_"));
}

let refreshInFlight: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    const refreshToken = getRefreshToken();
    if (!refreshToken) return false;
    const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) {
      clearSession();
      return false;
    }
    setSession((await response.json()) as LoginResponse);
    return true;
  })().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

async function request<T>(path: string, options: RequestInit = {}, auth = true, retry = true): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (auth) {
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  if (response.status === 401 && auth && retry) {
    if (isDemoToken(getToken())) clearSession();
    else if (await refreshSession()) return request<T>(path, options, auth, false);
  }
  if (response.status === 204) return undefined as T;

  const body = await response.json();
  if (!response.ok) throw new ApiError(response.status, body as ApiErrorBody);
  return body as T;
}

export function login(email: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>(
    "/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) },
    false,
  );
}

export function me(): Promise<MeResponse> {
  return request<MeResponse>("/auth/me", { method: "GET" });
}

export function listDemoPersonas(): Promise<DemoPersona[]> {
  return request<DemoPersona[]>("/demo/personas", { method: "GET" }, false);
}

export async function selectDemoPersona(personaSlug: string): Promise<DemoSessionResponse | null> {
  const savedToken = getSavedDemoSessions()[personaSlug];
  if (savedToken) {
    activateDemoToken(savedToken);
    try {
      const profile = await me();
      if (profile.is_demo && profile.persona_slug === personaSlug) return null;
    } catch {
      // Expired and invalid sessions are replaced below.
    }
    removeDemoToken(personaSlug);
    clearSession();
  }

  const session = await request<DemoSessionResponse>(
    "/demo/sessions",
    { method: "POST", body: JSON.stringify({ persona_slug: personaSlug }) },
    false,
  );
  saveDemoToken(personaSlug, session.token);
  activateDemoToken(session.token);
  return session;
}

export function listDemoOutbox(): Promise<DemoDelivery[]> {
  return request<DemoDelivery[]>("/demo/outbox", { method: "GET" });
}

export function logout(): Promise<void> {
  return request<void>("/auth/logout", { method: "POST" });
}

export function listConversations(): Promise<ConversationSummary[]> {
  return request<ConversationSummary[]>("/conversations", { method: "GET" });
}

export function createConversation(): Promise<ConversationSummary> {
  return request<ConversationSummary>("/conversations", {
    method: "POST",
    body: JSON.stringify({ title: "New conversation" }),
  });
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/conversations/${id}`, { method: "GET" });
}

export function deleteConversation(id: string): Promise<void> {
  return request<void>(`/conversations/${id}`, { method: "DELETE" });
}

export async function streamChatMessage(
  conversationId: string,
  message: string,
  onEvent: (event: TraceEvent) => void,
  retry = true,
): Promise<ChatResponse> {
  const headers = new Headers({ "Content-Type": "application/json" });
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({ conversation_id: conversationId, message }),
  });
  if (response.status === 401 && retry) {
    if (isDemoToken(getToken())) clearSession();
    else if (await refreshSession()) return streamChatMessage(conversationId, message, onEvent, false);
  }
  if (!response.ok) {
    const body = await response.json();
    throw new ApiError(response.status, body as ApiErrorBody);
  }
  if (!response.body) throw new Error("Streaming response has no body.");

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

export function confirmPending(conversationId: string, agent: string): Promise<AgentResultResponse> {
  return request<AgentResultResponse>("/pending/confirm", {
    method: "POST",
    body: JSON.stringify({ conversation_id: conversationId, agent }),
  });
}

export function cancelPending(conversationId: string, agent: string): Promise<AgentResultResponse> {
  return request<AgentResultResponse>("/pending/cancel", {
    method: "POST",
    body: JSON.stringify({ conversation_id: conversationId, agent }),
  });
}

export function revisePending(
  conversationId: string,
  agent: string,
  editInstructions: string,
): Promise<AgentResultResponse> {
  return request<AgentResultResponse>("/pending/revise", {
    method: "POST",
    body: JSON.stringify({ conversation_id: conversationId, agent, edit_instructions: editInstructions }),
  });
}
