import type { ChatTurn } from "./types";

// sessionStorage, not localStorage (Component 9 decision) — the rendered transcript is a display
// convenience tied to one tab's session, not something that should follow the user's token across
// browser restarts. Independent of the backend's own ConversationMemory (learnings.md #7), which
// is what actually drives follow-up-question routing regardless of whether this local copy exists.
const TRANSCRIPT_STORAGE_KEY = "enterprise-ai-transcript";

export function loadTranscript(): ChatTurn[] {
  if (typeof window === "undefined") return [];
  const raw = window.sessionStorage.getItem(TRANSCRIPT_STORAGE_KEY);
  if (!raw) return [];
  try {
    return JSON.parse(raw) as ChatTurn[];
  } catch {
    return [];
  }
}

export function saveTranscript(turns: ChatTurn[]): void {
  window.sessionStorage.setItem(TRANSCRIPT_STORAGE_KEY, JSON.stringify(turns));
}

export function clearTranscript(): void {
  window.sessionStorage.removeItem(TRANSCRIPT_STORAGE_KEY);
}
