"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  cancelPending,
  clearToken,
  confirmPending,
  getToken,
  logout as apiLogout,
  me,
  revisePending,
  sendChatMessage,
} from "@/lib/api";
import { clearTranscript, loadTranscript, saveTranscript } from "@/lib/transcript";
import type { AgentResultResponse, ChatTurn } from "@/lib/types";
import { AgentReply } from "@/components/AgentReply";
import { ChatInput } from "@/components/ChatInput";
import { PendingActionCard } from "@/components/PendingActionCard";

interface PendingRef {
  turnId: string;
  agentName: string;
}

export default function ChatPage() {
  const router = useRouter();
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [showCitations, setShowCitations] = useState(false);
  const [sending, setSending] = useState(false);
  const [pendingBusy, setPendingBusy] = useState(false);
  const [pending, setPending] = useState<PendingRef | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.replace("/login");
      return;
    }

    me()
      .then((res) => setDisplayName(res.display_name))
      .catch(() => {
        clearToken();
        router.replace("/login");
      });

    const restored = loadTranscript();
    setTurns(restored);
    setPending(findPendingInTurns(restored));
  }, [router]);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ block: "end" });
  }, [turns, pending]);

  function updateTurns(next: ChatTurn[]) {
    setTurns(next);
    saveTranscript(next);
  }

  function updateTurnResult(turnId: string, agentName: string, result: AgentResultResponse) {
    updateTurns(
      turns.map((turn) =>
        turn.id === turnId ? { ...turn, results: { ...turn.results, [agentName]: result } } : turn
      )
    );
  }

  async function handleLogout() {
    try {
      await apiLogout();
    } catch {
      // token may already be invalid/expired — logging out locally still succeeds either way
    }
    clearToken();
    clearTranscript();
    router.replace("/login");
  }

  async function handleSend(message: string) {
    setError(null);
    setSending(true);
    try {
      const response = await sendChatMessage(message);
      const turn: ChatTurn = {
        id: crypto.randomUUID(),
        userMessage: message,
        routedTo: response.routed_to,
        results: response.results,
      };
      const next = [...turns, turn];
      updateTurns(next);
      setPending(findPendingInTurns(next));
    } catch (err) {
      handleApiError(err);
    } finally {
      setSending(false);
    }
  }

  async function handleConfirm() {
    if (!pending) return;
    setPendingBusy(true);
    try {
      const result = await confirmPending(pending.agentName);
      updateTurnResult(pending.turnId, pending.agentName, result);
      setPending(null);
    } catch (err) {
      handleApiError(err);
    } finally {
      setPendingBusy(false);
    }
  }

  async function handleCancel() {
    if (!pending) return;
    setPendingBusy(true);
    try {
      const result = await cancelPending(pending.agentName);
      updateTurnResult(pending.turnId, pending.agentName, result);
      setPending(null);
    } catch (err) {
      handleApiError(err);
    } finally {
      setPendingBusy(false);
    }
  }

  async function handleRevise(editInstructions: string) {
    if (!pending) return;
    setPendingBusy(true);
    try {
      const result = await revisePending(pending.agentName, editInstructions);
      updateTurnResult(pending.turnId, pending.agentName, result);
      setPending(result.requires_confirmation ? pending : null);
    } catch (err) {
      handleApiError(err);
    } finally {
      setPendingBusy(false);
    }
  }

  function handleApiError(err: unknown) {
    if (err instanceof ApiError && err.status === 401) {
      clearToken();
      router.replace("/login");
      return;
    }
    if (err instanceof ApiError) {
      setError(err.message);
      return;
    }
    setError("Something went wrong reaching the server. Please try again.");
  }

  return (
    <div className="chat-page">
      <header className="chat-header">
        <h1>Enterprise AI Assistant</h1>
        <div className="header-right">
          {displayName && <span>{displayName}</span>}
          <label className="toggle-label">
            <input type="checkbox" checked={showCitations} onChange={(e) => setShowCitations(e.target.checked)} />
            Show citations
          </label>
          <button className="text-button" onClick={handleLogout}>
            Logout
          </button>
        </div>
      </header>

      <div className="chat-body">
        <div className="chat-scroll-inner">
          {turns.length === 0 && <p className="empty-state">Ask a question to get started.</p>}

          {turns.map((turn) => (
            <div key={turn.id} style={{ display: "contents" }}>
              <div className="user-message">{turn.userMessage}</div>
              {Object.entries(turn.results).map(([agentName, result]) =>
                result.requires_confirmation && pending?.turnId === turn.id && pending.agentName === agentName ? (
                  <PendingActionCard
                    key={agentName}
                    agentName={agentName}
                    content={result.content}
                    busy={pendingBusy}
                    onConfirm={handleConfirm}
                    onCancel={handleCancel}
                    onRevise={handleRevise}
                  />
                ) : (
                  <AgentReply key={agentName} agentName={agentName} result={result} showCitations={showCitations} />
                )
              )}
            </div>
          ))}

          {sending && <div className="typing-indicator">Thinking...</div>}
          <div ref={scrollRef} />
        </div>
      </div>

      {error && <div className="inline-error">{error}</div>}
      <ChatInput disabled={sending || pending !== null} onSend={handleSend} />
    </div>
  );
}

function findPendingInTurns(turns: ChatTurn[]): PendingRef | null {
  for (let i = turns.length - 1; i >= 0; i--) {
    const turn = turns[i];
    for (const [agentName, result] of Object.entries(turn.results)) {
      if (result.requires_confirmation) {
        return { turnId: turn.id, agentName };
      }
    }
  }
  return null;
}
