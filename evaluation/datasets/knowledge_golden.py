"""Golden dataset for Knowledge Agent RAG evaluation (learnings.md #11).

Every case is a real fact drawn from `tests/fixtures/knowledge_docs/` and, where noted, a real bug
this project already found and fixed via manual live testing (learnings.md #3) — this dataset
turns those into a permanent regression suite instead of a one-off manual check.

`expected_source_doc` is checked against citation strings shaped `"<filename>::<chunk_index>"`
(confirmed via tests/unit/test_knowledge_agent.py) using `citation.startswith(expected_source_doc)`.
`expected_output` is a short reference answer used by DeepEval's ContextualRecall/Precision
metrics, not an exact-match string.
"""

from __future__ import annotations

KNOWLEDGE_GOLDEN_CASES: list[dict] = [
    {
        "question": "How many PTO days do I get in the US?",
        "expected_source_doc": "pto_policy_us.md",
        "expected_output": "US full-time employees accrue 15 days of PTO per year (1.25 days/month), with up to 5 days carrying over to the next year.",
        "expect_answer_found": True,
        "note": "Baseline retrieval.",
    },
    {
        "question": "What is the India leave policy?",
        "expected_source_doc": "pto_policy_india.md",
        "expected_output": "India employees get 18 Earned Leave, 12 Casual Leave, and 12 Sick Leave days per year. EL carries forward up to 45 days; CL/SL reset January 1.",
        "expect_answer_found": True,
        "note": "US/India disambiguation — near-duplicate topic, two documents both about PTO.",
    },
    {
        "question": "What's the domestic travel per diem?",
        "expected_source_doc": "travel_policy.md",
        "expected_output": "The domestic per diem is $60/day (international is $85/day).",
        "expect_answer_found": True,
        "note": "Baseline retrieval.",
    },
    {
        "question": "Can I work from home on Fridays?",
        "expected_source_doc": "remote_work_policy.md",
        "expected_output": "Yes — the policy is hybrid, with Monday and Friday remote-optional (Tue/Wed/Thu in-office if within 50 miles).",
        "expect_answer_found": True,
        "note": "Regression: the abbreviation/vocabulary retrieval gap (learnings.md #3) — 'work from home' vs. the doc's actual wording ('remote', 'hybrid').",
    },
    {
        "question": "What's the per-day reimbursement rate for client meals when traveling domestically?",
        "expected_source_doc": "expense_policy.md",
        "expected_output": "Client meals are reimbursed up to $75 per person, not the general $60/day travel per diem.",
        "expect_answer_found": True,
        "note": "Regression: the category-overlap reasoning bug (learnings.md #3) — must defer to the more specific expense-policy rule, not the general travel per diem.",
    },
    {
        "question": "Is my home internet bill reimbursable?",
        "expected_source_doc": "expense_policy.md",
        "expected_output": "No — home internet is not listed as a reimbursable expense category.",
        "expect_answer_found": None,  # documented calibration shift (learnings.md #3) — conclusion should be "no" either way; not asserted strictly
        "note": "Calibration-tracking case, not a strict pass/fail on answer_found.",
    },
    {
        "question": "How long until my 401k match vests?",
        "expected_source_doc": "faq_benefits.txt",
        "expected_output": "The 401k match (4% of salary, dollar-for-dollar) vests immediately.",
        "expect_answer_found": True,
        "note": "Coverage case — a doc with no prior eval/bug history.",
    },
    {
        "question": "How soon after an incident is a postmortem scheduled?",
        "expected_source_doc": "runbook_oncall_incident.md",
        "expected_output": "A postmortem is scheduled within 3 business days for Sev1/Sev2 incidents.",
        "expect_answer_found": True,
        "note": "Coverage case — an ops/runbook doc, a different register from the HR-policy-heavy cases above.",
    },
    {
        "question": "What's the weather like on Mars?",
        "expected_source_doc": None,
        "expected_output": "",
        "expect_answer_found": False,
        "note": "Hallucination-resistance baseline — genuinely out of scope, should return answer_found=False with no citations.",
    },
]
