export interface AgentResultResponse {
  content: string;
  citations: string[];
  requires_confirmation: boolean;
}

export interface ChatResponse {
  conversation_id: string;
  turn_id: number;
  routed_to: string[];
  results: Record<string, AgentResultResponse>;
}

export interface LoginResponse {
  token: string;
  refresh_token: string;
  expires_in: number;
  display_name: string;
}

export interface MeResponse {
  user_id: string;
  email: string;
  display_name: string;
  employee_role: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationTurnResponse {
  id: number;
  user_message: string;
  routed_to: string[];
  results: Record<string, AgentResultResponse>;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  turns: ConversationTurnResponse[];
}

export interface ApiErrorBody {
  error: string;
  agent?: string;
}

export interface ChatTurn {
  id: number;
  userMessage: string;
  routedTo: string[];
  results: Record<string, AgentResultResponse>;
}

export type TraceEvent =
  | { type: "routing_decided"; agents: string[]; reasoning: string }
  | { type: "agent_started"; agent: string }
  | { type: "agent_finished"; agent: string }
  | { type: "tool_called"; agent: string; tool: string; detail?: string }
  | { type: "tool_result"; agent: string; tool: string; detail?: string }
  | { type: "done"; result: ChatResponse }
  | { type: "error"; error: string };
