from __future__ import annotations

from enterprise_ai.core.agent import AgentResult
from enterprise_ai.orchestrator.memory import ConversationMemory


def test_empty_memory_produces_no_history():
    memory = ConversationMemory()

    assert memory.as_messages() == []
    assert memory.as_text_summary() == ""


def test_single_turn_produces_user_and_tagged_assistant_message():
    memory = ConversationMemory()

    memory.add_turn("What's Priya's salary?", {"database": AgentResult(agent_name="database", content="$71,100.")})

    assert memory.as_messages() == [
        {"role": "user", "content": "What's Priya's salary?"},
        {"role": "assistant", "content": "database: $71,100."},
    ]
    assert "database: $71,100." in memory.as_text_summary()


def test_multi_agent_turn_tags_each_agent_by_name():
    memory = ConversationMemory()

    memory.add_turn(
        "average salary and send a Slack update",
        {
            "database": AgentResult(agent_name="database", content="$106,407."),
            "communication": AgentResult(agent_name="communication", content="Sent."),
        },
    )

    assistant_message = memory.as_messages()[1]["content"]
    assert "database: $106,407." in assistant_message
    assert "communication: Sent." in assistant_message


def test_rolling_window_drops_oldest_turns_beyond_max():
    memory = ConversationMemory(max_turns=2)

    for i in range(4):
        memory.add_turn(f"question {i}", {"knowledge": AgentResult(agent_name="knowledge", content=f"answer {i}")})

    messages = memory.as_messages()
    assert len(messages) == 2 * 2  # 2 turns kept, user+assistant each
    assert messages[0]["content"] == "question 2"
    assert messages[2]["content"] == "question 3"
