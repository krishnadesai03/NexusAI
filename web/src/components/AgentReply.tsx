import type { AgentResultResponse } from "@/lib/types";

// The label always reads "AI Assistant" regardless of which agent (knowledge/performance/
// database/communication) actually answered — routing is an internal implementation detail the
// user shouldn't have to think about turn to turn.
export function AgentReply({ result, showCitations }: { result: AgentResultResponse; showCitations: boolean }) {
  return (
    <div className="agent-reply">
      <span className="message-label">AI Assistant</span>
      {result.content}
      {showCitations && result.citations.length > 0 && (
        <div className="citations">
          Sources
          <ul>
            {result.citations.map((citation, i) => (
              <li key={i}>{citation}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
