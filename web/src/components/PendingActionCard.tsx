"use client";

import { useState } from "react";

export function PendingActionCard({
  content,
  busy,
  onConfirm,
  onCancel,
  onRevise,
}: {
  content: string;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  onRevise: (editInstructions: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");

  function submitRevision() {
    if (!editText.trim()) return;
    onRevise(editText.trim());
    setEditText("");
    setEditing(false);
  }

  return (
    <div className="pending-card">
      <span className="message-label">AI Assistant — awaiting your confirmation</span>
      {content}

      {editing ? (
        <div className="revise-row">
          <input
            autoFocus
            placeholder="Describe your change..."
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitRevision()}
            disabled={busy}
          />
          <button onClick={submitRevision} disabled={busy || !editText.trim()}>
            Submit revision
          </button>
        </div>
      ) : (
        <div className="pending-actions">
          <button className="send-button" onClick={onConfirm} disabled={busy}>
            Send it
          </button>
          <button onClick={() => setEditing(true)} disabled={busy}>
            Edit
          </button>
          <button className="cancel-button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
