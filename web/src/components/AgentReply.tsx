import type { AgentResultResponse } from "@/lib/types";

export function AgentReply({
  agentName,
  result,
  showCitations,
}: {
  agentName: string;
  result: AgentResultResponse;
  showCitations: boolean;
}) {
  return (
    <div className="agent-reply">
      <span className="agent-name">{agentName}</span>
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
