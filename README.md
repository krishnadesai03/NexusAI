# Nexus AI — AI Internal Company Assistant

**Current version: 0.4.0** — public role-based demo workflow

An orchestrator that routes employee requests to specialized sub-agents — knowledge/RAG,
performance/Atlassian, database/SQL, and communication — and fans the results back into one
response. Built to demonstrate real multi-agent orchestration patterns (hybrid routing, parallel
fan-out, tool-calling loops, human-in-the-loop confirmation, live tracing) using hand-rolled
`asyncio`.

Live: backend on [Render](https://nexusai-api-ctud.onrender.com) (`GET /health`), frontend on
[Vercel](https://nexus-ai-sand-nine.vercel.app).

## Overview

Instead of one large model trying to do everything, requests are routed to whichever
specialized agent(s) actually own the answer:

- **Knowledge Agent** — answers questions from static company-policy documents (PTO, expenses,
  onboarding, runbooks) via retrieval-augmented generation.
- **Performance Agent** — answers questions about sprint velocity, ticket activity, and commit
  history against a real Jira/Confluence/Bitbucket sandbox.
- **Database Agent** — answers questions about structured company data (employees, deals,
  expenses, support tickets) by writing and running real, read-only SQL.
- **Communication Agent** — drafts Slack messages and emails behind a human confirmation step.
  Public demo confirmations are captured in a session-owned Demo Outbox and never reach real
  external accounts.

A hybrid router (an LLM reasoning about intent, constrained to a validated schema of real agent
names) decides which agent(s) handle a given request — a single request can fan out to more than
one agent at once, running concurrently. Every step of that process — routing, agent start/finish,
tool calls — streams live to the frontend over Server-Sent Events.

## Features

- **Hybrid, schema-guarded routing** — an LLM reasons about intent, but its decision is forced
  through a strict schema before anything acts on it; invalid output is retried, never trusted.
- **Concurrent multi-agent fan-out** — a single request can route to several agents at once, all
  running in parallel via `asyncio.gather`.
- **Real tool-calling agents** — Performance, Database, and Communication agents run genuine
  multi-turn tool-calling loops, not single-shot prompts, gathering data across several lookups
  before answering.
- **Layered guardrails per agent** — a groundedness flag for RAG answers, a stacked
  judgment-call → regex-filter → read-only-database-role guardrail for SQL, and a
  destination-never-LLM-controlled rule for messaging.
- **Human-in-the-loop confirmation** — the Communication Agent only ever stages a draft; nothing
  sends until an explicit Send / Edit / Cancel decision.
- **Anonymous, persona-owned demo sessions** — visitors choose Sofia Reyes (Employee) or Matt
  Davidson (Executive) without credentials. Each browser retains an independent session per
  persona, while inactive demo conversations and captured messages expire after 24 hours.
- **Role-based access control enforced before tools run** — knowledge retrieval, database
  credentials/views, and agent capabilities are selected from the active persona. Access is not
  left to prompt instructions alone.
- **Session-scoped tool-result caching + parallel tool calls** — independent tool calls within one
  turn run concurrently, and repeated lookups within the same conversation are memoized instead of
  re-fetched.
- **Live orchestration trace** — routing decisions, agent start/finish, and every tool call stream
  to the frontend in real time as they happen, not just after the whole request finishes.
- **A recruiter-friendly web app** — public persona landing page, persistent chat, live trace
  panel, profile switching, and a visible Demo Outbox for confirmed Slack/email simulations,
  backed by a FastAPI API and a Next.js frontend.
- **An evaluation harness** — DeepEval-based RAG metrics (contextual precision/recall,
  faithfulness, answer relevancy) for the Knowledge Agent, and LLM-judge correctness checks for
  Performance and Database agents, built as a regression suite from real bugs found during
  development.

## Tech Stack

**Backend**
- Python 3.11+, `asyncio`
- FastAPI (web API, Server-Sent Events streaming)
- OpenAI API (`gpt-4.1-mini` for reasoning/generation, `text-embedding-3-small` for embeddings)
- Pydantic (schema-guarded structured outputs)
- PostgreSQL + `pgvector` (vector store and structured company data)
- Atlassian Remote MCP Server (Jira/Confluence), via the official `mcp` SDK
- `httpx` (Bitbucket REST, Slack API, Resend email API)
- DeepEval (RAG and agent-correctness evaluation)

**Frontend**
- Next.js, React, TypeScript
- Server-Sent Events client for the live trace panel

**Infrastructure**
- Docker Compose (local Postgres + pgvector)
- Supabase (deployed Postgres + pgvector), Render (backend), Vercel (frontend) — all
  dashboard-configured, no IaC

## Architecture

![Nexus AI architecture diagram](./NexusAI_architecture.png)

A request comes in from the frontend, passes through the API to the Orchestrator, which decides
via the Router which agent(s) should handle it and runs them in parallel. Each agent reaches into
its own data sources (Jira/Confluence via MCP, Bitbucket via REST, Postgres, Slack/Resend), and
every step — routing, agent progress, tool calls, the final response — streams back to the
frontend live over Server-Sent Events.

Every agent implements the same `Agent` protocol (`async def handle(...)`), so the orchestrator
never needs to know about concrete agent implementations — only the interface. Domain logic never
imports a vendor SDK directly: an `LLMClient` protocol sits in front of OpenAI, an
`EmbeddingClient` protocol in front of the embedding API, and a `VectorStore` protocol in front of
pgvector, each with exactly one real adapter. This is what makes every agent testable with fakes
instead of live API calls.

The active persona is resolved into a typed capability set before an agent or data adapter is
constructed. Sofia can retrieve company and Engineering documents, use the shared Engineering
performance fixtures, see a safe company directory plus her own full database profile, and read
anonymized support operations. Matt can retrieve company, department, and executive documents and
use the full read-only business database. Both personas can stage communications.

The Communication Agent is the only workflow shaped like a side effect, so it gets two extra
guardrails the read-only agents don't need: the LLM never controls an arbitrary destination, and
nothing happens immediately—`handle()` only stages a pending draft. For anonymous demo sessions,
confirmation writes the rendered Slack/email message to `demo_deliveries`; real Slack and Resend
clients are never invoked.

## Project Structure

```
enterprise-ai/
├── src/enterprise_ai/
│   ├── orchestrator/         # Router, Orchestrator, bounded prompt memory, schemas
│   ├── agents/
│   │   ├── knowledge/        # RAG agent
│   │   ├── performance/      # Jira/Confluence/Bitbucket tool-calling agent
│   │   ├── database/         # SQL tool-calling agent
│   │   └── communication/    # Slack/email agent with HITL confirmation
│   ├── core/                 # Agent/LLMClient/EmbeddingClient protocols, ToolCache, retry logic
│   ├── integrations/         # Concrete adapters: pgvector, Atlassian MCP/REST, Postgres, Slack/Resend
│   └── bootstrap.py          # Shared resource + per-session wiring, reused by every entry point
├── api/                       # FastAPI backend (demo sessions, durable chat, outbox, chat/SSE)
├── web/                        # Next.js frontend
├── evaluation/                 # DeepEval-based RAG and agent-correctness evaluation harness
├── scripts/                    # CLI chat client, live smoke tests, data-seeding scripts
├── supabase/migrations/        # Versioned persistence schema, RLS policies, grants
├── tests/unit/                 # Fake-backed unit tests (no network calls, no API key required)
├── docker-compose.yml          # Local Postgres + pgvector
├── pyproject.toml              # Python dependencies (source of truth)
└── .env.example                # All required environment variables, documented
```

## Getting Started

**Requirements:** Python ≥ 3.11, Node.js (for the frontend), Docker (for local Postgres).

```bash
# 1. Set up the Python environment
py -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"

# 2. Start Postgres + pgvector (required for the Knowledge and Database agents)
docker compose up -d postgres

# 3. Configure environment variables
cp .env.example .env
# fill in OPENAI_API_KEY at minimum; see .env.example for what each component needs
```

The Performance Agent additionally needs a real Atlassian Cloud site (Jira + Confluence) and a
Bitbucket workspace — account setup is manual (see `.env.example`'s Atlassian section), after
which the seeding scripts under `scripts/` populate it with synthetic data. The Communication
Agent needs a Slack bot token and a Resend API key. Real email delivery also requires
`EMAIL_FROM_ADDRESS` to use a custom domain verified in Resend; a normal `gmail.com` sender will
be rejected (see `.env.example`'s Communication Agent section).

### Supabase setup

The web application uses Supabase for anonymous demo sessions, durable conversations, pending
actions, and the Demo Outbox. Legacy credential authentication remains available at the API level
but is intentionally not exposed in the public UI:

1. Create a Supabase project and copy its writable Postgres connection string into `DATABASE_URL`.
2. Copy the project URL and publishable API key into `SUPABASE_URL` and
   `SUPABASE_PUBLISHABLE_KEY`.
3. Apply the versioned schema and row-level security policies:

   ```bash
   .venv/Scripts/python.exe scripts/apply_supabase_migrations.py
   ```

4. Seed the synthetic knowledge and company database fixtures. The seeders attach knowledge
   access labels and create the separate employee/executive read-only database surfaces.

   ```bash
   .venv/Scripts/python.exe scripts/seed_knowledge_fixtures.py
   .venv/Scripts/python.exe scripts/push_database_fixtures.py
   ```

## Usage

**CLI chat client** (fastest way to try every agent from one terminal):

```bash
.venv/Scripts/python.exe scripts/chat.py
```

**Full public demo web app** (no visitor credentials required):

```bash
.venv/Scripts/python.exe -m uvicorn api.main:app --reload --port 8000
cd web && npm install && npm run dev   # in a separate terminal — serves http://localhost:3000
```

Open `http://localhost:3000`, choose Sofia Reyes or Matt Davidson, and the browser will create or
reuse that persona's anonymous demo session. Choosing **Switch profile** preserves each persona's
token independently, so returning to either profile within the active window restores only that
profile's conversations.

Example questions to try, one per agent:

- *"What's our PTO policy in the US?"* → Knowledge Agent
- *"How many tickets did Priya Nair complete in sprint 6?"* → Performance Agent
- *"What's the average expense claim amount this quarter?"* → Database Agent
- *"Post a Slack message letting the team know the demo went well."* → Communication Agent,
  stages a draft and waits for confirmation; confirming captures it in Demo Outbox without
  contacting Slack

A single request can also span more than one agent at once — e.g. *"Compare last sprint's
velocity to what the docs promised"* routes to both Performance and Knowledge concurrently.

## Future Improvements

- **Deployment automation** — GitHub Actions is configured to run the offline unit suite and Ruff
  on pushes and pull requests. Render/Vercel still auto-deploy from git without committed
  infrastructure-as-code or an automated deployed smoke-test gate.
- **Caching for the Knowledge Agent and repeated database questions** — tool-result caching for
  the Performance/Database agents is already in place; embedding-query caching and a
  question-to-SQL cache (for literal repeat questions) are still open.
- **Bitbucket over MCP** — Jira and Confluence now go through Atlassian's Remote MCP Server;
  Bitbucket Cloud support exists there too, but requires linking the Bitbucket workspace to the
  Atlassian organization first (a one-time dashboard step not yet done), so it still uses direct
  REST for now.
- **Agentic tracing metrics** — the evaluation harness currently checks answer correctness;
  tool-use-correctness and task-completion metrics (which need additional instrumentation) aren't
  wired up yet.
- Long-conversation summarization beyond the current persisted-history + five-turn prompt window
