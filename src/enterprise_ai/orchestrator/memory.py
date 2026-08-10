from __future__ import annotations

from dataclasses import dataclass

from enterprise_ai.core.agent import AgentResult

MAX_TURNS = 5


@dataclass
class _Turn:
    user_request: str
    agent_answers: dict[str, str]  # agent_name -> final answer content, tagged since one turn
    # can fan out to more than one agent at once


class ConversationMemory:
    """Session-only conversation history (learnings.md #7) — lives only for the lifetime of one
    running Orchestrator/process, lost on exit; no persistence to disk. Lives at the Orchestrator
    level, not per-agent, since a follow-up question can route to a completely different agent
    than the one before it — a per-agent history would break that continuity the moment routing
    switches (e.g. a database question followed by a performance question about the same person).

    Keeps only the last `max_turns` turns (FIFO-trimmed) to bound prompt growth in a long
    session — no summarization/compaction, just a hard rolling window."""

    def __init__(self, max_turns: int = MAX_TURNS) -> None:
        self._max_turns = max_turns
        self._turns: list[_Turn] = []

    def add_turn(self, user_request: str, results: dict[str, AgentResult]) -> None:
        answers = {name: result.content for name, result in results.items()}
        self._turns.append(_Turn(user_request=user_request, agent_answers=answers))
        if len(self._turns) > self._max_turns:
            self._turns = self._turns[-self._max_turns :]

    def as_messages(self) -> list[dict]:
        """OpenAI chat-message shape (the codebase's existing convention for every tool-calling
        loop) — the canonical form every agent receives via Agent.handle()'s `history` param.
        Agents that call the LLM with a single prompt string instead (KnowledgeAgent, Router)
        convert this into text themselves rather than this class exposing a second shape."""
        messages: list[dict] = []
        for turn in self._turns:
            messages.append({"role": "user", "content": turn.user_request})
            assistant_content = "\n".join(f"{name}: {answer}" for name, answer in turn.agent_answers.items())
            messages.append({"role": "assistant", "content": assistant_content})
        return messages

    def as_text_summary(self) -> str:
        """Plain-text form, for callers that only take a single prompt string (Router)."""
        if not self._turns:
            return ""
        lines: list[str] = []
        for turn in self._turns:
            lines.append(f"User: {turn.user_request}")
            for name, answer in turn.agent_answers.items():
                lines.append(f"{name}: {answer}")
        return "\n".join(lines)
