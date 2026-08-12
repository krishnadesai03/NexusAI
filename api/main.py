"""FastAPI entry point for the web backend (learnings.md Component 9). Wires the same
enterprise_ai.bootstrap machinery scripts/chat.py uses, but builds shared resources once at
startup and a fresh session (Orchestrator + ConversationMemory + CommunicationAgent) per login,
so concurrent employees never share mutable conversation/pending-action state — see
enterprise_ai/bootstrap.py's module docstring for why that split exists.

Local dev:
    docker compose up -d postgres
    .venv/Scripts/python.exe -m uvicorn api.main:app --reload --port 8000
Render deployment reads all the same env vars from its dashboard instead of a .env file.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.auth import router as auth_router
from api.chat import router as chat_router
from api.pending import router as pending_router
from api.sessions import SessionStore
from enterprise_ai.bootstrap import build_shared_resources, close_shared_resources

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(ROOT / ".env")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.shared = await build_shared_resources()
    app.state.sessions = SessionStore()
    yield
    await close_shared_resources(app.state.shared)


app = FastAPI(title="Enterprise AI Assistant API", lifespan=lifespan)

_frontend_origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_frontend_origin],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Normalizes every error response to {"error": ...} — the locked API contract — since
    FastAPI's default is {"detail": ...} and some routes (the 409 pending-conflict guard) also
    need to attach an extra field like `agent`."""
    body = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=body)


app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(pending_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
