"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ApiError,
  cancelPending,
  clearSession,
  confirmPending,
  createConversation,
  deleteConversation,
  getConversation,
  getToken,
  listConversations,
  me,
  revisePending,
  streamChatMessage,
} from "@/lib/api";
import { applyTraceEvent, emptyTrace, type Trace } from "@/lib/trace";
import type { AgentResultResponse, ChatTurn, ConversationSummary, MeResponse } from "@/lib/types";
import { AgentReply } from "@/components/AgentReply";
import { ChatInput } from "@/components/ChatInput";
import { PendingActionCard } from "@/components/PendingActionCard";
import { TracePanel } from "@/components/TracePanel";

interface PendingRef {
  turnId: number;
  agentName: string;
}

export default function ChatPage() {
  const router = useRouter();
  const [profile, setProfile] = useState<MeResponse | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCitations, setShowCitations] = useState(false);
  const [working, setWorking] = useState(false);
  const [trace, setTrace] = useState<Trace>(emptyTrace());
  const [sending, setSending] = useState(false);
  const [pendingBusy, setPendingBusy] = useState(false);
  const [pending, setPending] = useState<PendingRef | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/");
      return;
    }

    async function initialize() {
      try {
        const user = await me();
        setProfile(user);
        let items = await listConversations();
        if (items.length === 0) items = [await createConversation()];
        setConversations(items);
        await openConversation(items[0].id);
      } catch (err) {
        handleApiError(err);
      } finally {
        setLoading(false);
      }
    }
    void initialize();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ block: "end" });
  }, [turns, pending]);

  async function openConversation(id: string) {
    setError(null);
    const detail = await getConversation(id);
    const restored: ChatTurn[] = detail.turns.map((turn) => ({
      id: turn.id,
      userMessage: turn.user_message,
      routedTo: turn.routed_to,
      results: turn.results,
    }));
    setActiveConversationId(id);
    setTurns(restored);
    setPending(findPendingInTurns(restored));
    setTrace(emptyTrace());
  }

  async function handleNewConversation() {
    try {
      const created = await createConversation();
      setConversations((current) => [created, ...current]);
      setActiveConversationId(created.id);
      setTurns([]);
      setPending(null);
      setTrace(emptyTrace());
    } catch (err) {
      handleApiError(err);
    }
  }

  async function handleDeleteConversation(id: string) {
    try {
      await deleteConversation(id);
      let remaining = conversations.filter((conversation) => conversation.id !== id);
      if (remaining.length === 0) remaining = [await createConversation()];
      setConversations(remaining);
      if (activeConversationId === id) await openConversation(remaining[0].id);
    } catch (err) {
      handleApiError(err);
    }
  }

  function updateTurnResult(turnId: number, agentName: string, result: AgentResultResponse) {
    setTurns((current) =>
      current.map((turn) =>
        turn.id === turnId ? { ...turn, results: { ...turn.results, [agentName]: result } } : turn,
      ),
    );
  }

  function handleSwitchProfile() {
    clearSession();
    router.push("/");
  }

  async function handleSend(message: string) {
    if (!activeConversationId) return;
    setError(null);
    setSending(true);
    setTrace(emptyTrace());
    try {
      const response = await streamChatMessage(activeConversationId, message, (event) => {
        setTrace((previous) => applyTraceEvent(previous, event));
      });
      const turn: ChatTurn = {
        id: response.turn_id,
        userMessage: message,
        routedTo: response.routed_to,
        results: response.results,
      };
      setTurns((current) => [...current, turn]);
      setPending(findPendingInTurns([...turns, turn]));
      setConversations(await listConversations());
    } catch (err) {
      handleApiError(err);
    } finally {
      setSending(false);
    }
  }

  async function handleConfirm() {
    if (!pending || !activeConversationId) return;
    setPendingBusy(true);
    try {
      const result = await confirmPending(activeConversationId, pending.agentName);
      updateTurnResult(pending.turnId, pending.agentName, result);
      setPending(null);
    } catch (err) {
      handleApiError(err);
    } finally {
      setPendingBusy(false);
    }
  }

  async function handleCancel() {
    if (!pending || !activeConversationId) return;
    setPendingBusy(true);
    try {
      const result = await cancelPending(activeConversationId, pending.agentName);
      updateTurnResult(pending.turnId, pending.agentName, result);
      setPending(null);
    } catch (err) {
      handleApiError(err);
    } finally {
      setPendingBusy(false);
    }
  }

  async function handleRevise(editInstructions: string) {
    if (!pending || !activeConversationId) return;
    setPendingBusy(true);
    try {
      const result = await revisePending(activeConversationId, pending.agentName, editInstructions);
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
      clearSession();
      router.replace("/");
      return;
    }
    setError(err instanceof ApiError ? err.message : "Something went wrong reaching the server. Please try again.");
  }

  return (
    <div className="chat-page">
      <aside className="conversation-sidebar">
        <div className="conversation-sidebar-header">
          <span>Conversations</span>
          <button onClick={handleNewConversation} aria-label="New conversation">+</button>
        </div>
        <div className="conversation-list">
          {conversations.map((conversation) => (
            <div
              className={`conversation-row ${conversation.id === activeConversationId ? "active" : ""}`}
              key={conversation.id}
            >
              <button
                className="conversation-open"
                onClick={() => void openConversation(conversation.id)}
                disabled={sending || pendingBusy}
              >
                {conversation.title}
              </button>
              <button
                className="conversation-delete"
                onClick={() => void handleDeleteConversation(conversation.id)}
                disabled={sending || pendingBusy}
                aria-label={`Delete ${conversation.title}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      </aside>

      <div className="chat-main">
        <header className="chat-header">
          <div className="brand"><span className="brand-logo">N</span><h1>Nexus AI</h1></div>
          <div className="header-center">
            {profile && (
              <div className="active-profile">
                <span className="active-profile-name">{profile.display_name}</span>
                <span className="active-profile-role">{profile.title ?? profile.employee_role}</span>
              </div>
            )}
          </div>
          <div className="header-right">
            <label className="toggle-label">
              <input type="checkbox" checked={working} onChange={(event) => setWorking(event.target.checked)} />
              Working
            </label>
            <label className="toggle-label">
              <input
                type="checkbox"
                checked={showCitations}
                onChange={(event) => setShowCitations(event.target.checked)}
              />
              Show citations
            </label>
            <Link className="text-link" href="/outbox">Demo Outbox</Link>
            <button className="text-button" onClick={handleSwitchProfile}>Switch profile</button>
          </div>
        </header>

        <div className="demo-banner">
          <span>Demo mode</span> Communications are captured safely in Demo Outbox. Inactive history expires after 24 hours.
        </div>
        <div className="chat-body">
          <div className="chat-scroll-inner">
            {!loading && turns.length === 0 && <p className="empty-state">Ask a question to get started.</p>}
            {loading && <p className="empty-state">Loading your conversations...</p>}
            {turns.map((turn) => (
              <div key={turn.id} style={{ display: "contents" }}>
                <div className="user-message"><span className="message-label">You</span>{turn.userMessage}</div>
                {Object.entries(turn.results).map(([agentName, result]) =>
                  result.requires_confirmation && pending?.turnId === turn.id && pending.agentName === agentName ? (
                    <PendingActionCard
                      key={agentName}
                      content={result.content}
                      busy={pendingBusy}
                      onConfirm={handleConfirm}
                      onCancel={handleCancel}
                      onRevise={handleRevise}
                    />
                  ) : (
                    <AgentReply key={agentName} result={result} showCitations={showCitations} />
                  ),
                )}
              </div>
            ))}
            {sending && <div className="typing-indicator">Thinking...</div>}
            <div ref={scrollRef} />
          </div>
        </div>

        {error && <div className="inline-error">{error}</div>}
        <ChatInput disabled={loading || sending || pending !== null} onSend={handleSend} />
      </div>
      {working && <TracePanel trace={trace} />}
    </div>
  );
}

function findPendingInTurns(turns: ChatTurn[]): PendingRef | null {
  for (let index = turns.length - 1; index >= 0; index--) {
    const turn = turns[index];
    for (const [agentName, result] of Object.entries(turn.results)) {
      if (result.requires_confirmation) return { turnId: turn.id, agentName };
    }
  }
  return null;
}
