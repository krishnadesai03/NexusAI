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
