// Mirrors api/schemas.py exactly — the locked API contract from learnings.md's Component 9
// design discussion. Keep these two in sync by hand; there's no shared codegen between the
// Python backend and this frontend.

export interface AgentResultResponse {
  content: string;
  citations: string[];
  requires_confirmation: boolean;
}

export interface ChatResponse {
  routed_to: string[];
  results: Record<string, AgentResultResponse>;
}

export interface LoginResponse {
  token: string;
  display_name: string;
}

export interface MeResponse {
  display_name: string;
}

export interface ApiErrorBody {
  error: string;
  agent?: string;
}

// One rendered turn in the chat transcript, persisted to sessionStorage as-is (Component 9's
// "sessionStorage is fine" decision) — a user message plus every agent's reply to it, keyed the
// same way ChatResponse.results is.
export interface ChatTurn {
  id: string;
  userMessage: string;
  routedTo: string[];
  results: Record<string, AgentResultResponse>;
}

// Live orchestration-trace events streamed over /chat's SSE response (api/chat.py) — mirrors
// the plain dicts enterprise_ai.core.agent.emit_event sends. Powers the "Working" trace panel.
export type TraceEvent =
  | { type: "routing_decided"; agents: string[]; reasoning: string }
  | { type: "agent_started"; agent: string }
  | { type: "agent_finished"; agent: string }
  | { type: "tool_called"; agent: string; tool: string; detail?: string }
  | { type: "tool_result"; agent: string; tool: string; detail?: string }
  | { type: "done"; result: ChatResponse }
  | { type: "error"; error: string };
