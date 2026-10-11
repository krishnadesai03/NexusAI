"use client";

const STARTER_PROMPTS = [
  {
    agent: "Company knowledge",
    icon: "K",
    question: "I’m planning a client trip. What travel expenses are covered, and which ones need approval?",
  },
  {
    agent: "Team performance",
    icon: "P",
    question: "How has the Engineering team’s completed work changed over the last three sprints?",
  },
  {
    agent: "Company database",
    icon: "D",
    question: "Break down support tickets by priority and show how many have been resolved.",
  },
  {
    agent: "Communication",
    icon: "C",
    question: "Draft a Slack message thanking the team for their hard work this week.",
  },
] as const;

export function StarterPrompts({ onSelect }: { onSelect: (question: string) => void }) {
  return (
    <section className="starter-prompts" aria-labelledby="starter-prompts-title">
      <div className="starter-prompts-heading">
        <p className="starter-kicker">Explore Nexus AI</p>
        <h2 id="starter-prompts-title">What would you like to try?</h2>
        <p>Select a sample to place it in the message box. You can edit it before sending.</p>
      </div>
      <div className="starter-prompt-grid">
        {STARTER_PROMPTS.map((prompt) => (
          <button
            className="starter-prompt-card"
            key={prompt.agent}
            type="button"
            onClick={() => onSelect(prompt.question)}
          >
            <span className="starter-prompt-icon" aria-hidden="true">{prompt.icon}</span>
            <span className="starter-prompt-copy">
              <span className="starter-prompt-agent">{prompt.agent}</span>
              <span className="starter-prompt-question">{prompt.question}</span>
            </span>
            <span className="starter-prompt-arrow" aria-hidden="true">→</span>
          </button>
        ))}
      </div>
    </section>
  );
}
