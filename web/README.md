# Nexus AI web client

Next.js 16 frontend for the Nexus AI public role-based demo.

## User workflow

1. `/` loads the public Alderbrook Systems landing page and retrieves the available personas.
2. The visitor chooses Sofia Reyes (Employee) or Matt Davidson (Executive).
3. The browser reuses that persona's valid token or creates an anonymous demo session.
4. `/chat` restores only that session's active conversations and streams orchestration events.
5. Confirmed Slack/email drafts are captured at `/outbox`; no external message is sent.

The browser stores an independent opaque token for each persona in `localStorage`. **Switch
profile** clears only the active token, allowing either persona's conversation to be restored when
selected again. Invalid or expired tokens are discarded automatically. Demo conversations that
have been inactive for more than 24 hours are not returned by the API.

## Local development

Start the FastAPI backend from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000
```

In a second PowerShell terminal, start the frontend from this directory:

```powershell
cd web
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The client uses
`NEXT_PUBLIC_API_URL`, defaulting to `http://localhost:8000`.

## Routes

| Route | Purpose |
|---|---|
| `/` | Public persona chooser |
| `/chat` | Persona-scoped conversations and live trace |
| `/outbox` | Session-scoped simulated Slack/email deliveries |
| `/login` | Legacy URL; redirects to `/` |

## Verification

```powershell
npm run lint
npm run build
```
