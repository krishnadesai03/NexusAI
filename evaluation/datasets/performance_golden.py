"""Golden dataset for Performance Agent correctness evaluation (learnings.md #11).

Every case is a real, verified fact from the seeded Jira/Confluence/Bitbucket sandbox
(scripts/seed_performance_data.py, seed=42) and, where noted, a real bug this project already
found and fixed via manual live testing (learnings.md #4's follow-up sections).

`expected_citation_substring`, where present, is checked deterministically (plain Python, not an
LLM judge) against `AgentResult.metadata["citations"]` — citations here are real, programmatically
collected Jira keys/Confluence page refs/Bitbucket commit refs, not free text, so a substring match
is a cheaper and more reliable check than asking an LLM to judge citation correctness.
"""

from __future__ import annotations

PERFORMANCE_GOLDEN_CASES: list[dict] = [
    {
        "question": "How many tickets did Priya Nair complete in sprint 1?",
        "expected_output": "Priya Nair completed 2 tickets in sprint 1: KAN-2 and KAN-3, both Done.",
        "expected_citation_substring": "KAN-2",
        "note": "Verified live baseline (learnings.md #4).",
    },
    {
        "question": "Did anyone have an unusually quiet sprint, and what happened?",
        "expected_output": "Marcus Chen had zero tickets in Sprint 6; the sprint 6 retro notes he was on leave for most of the sprint.",
        "expected_citation_substring": None,
        "note": "The dataset's deliberately-injected anomaly case (learnings.md #4) — tests whether the agent checks Confluence retro pages, not just raw ticket counts.",
    },
    {
        "question": "How many bugs did Sofia Reyes fix across all sprints?",
        "expected_output": "Sofia Reyes fixed 15 bugs (she has 16 total Bug tickets, but one — KAN-111 — is still In Progress, not Done).",
        "expected_citation_substring": None,
        "note": "Regression: the 'fixed' (completed) vs. 'assigned' semantic-nuance bug (learnings.md #4).",
    },
    {
        "question": "How many commits mention billing?",
        "expected_output": "25 commits mention billing.",
        "expected_citation_substring": None,
        "note": "Regression: the miscounting bug (learnings.md #4) — the agent once correctly fetched all 25 matching commits but stated 29 in prose.",
    },
    {
        "question": "How many story points has Sofia Reyes completed across all sprints?",
        "expected_output": "0 — Sofia Reyes works only Tasks and Bugs (QA role), never story-pointed Story tickets.",
        "expected_citation_substring": None,
        "note": "Surprising but cleanly verifiable trick question — a real, deterministic fact from the seed data, not previously used as a test case.",
    },
]
