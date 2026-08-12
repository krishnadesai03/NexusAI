"use client";

import { useState, type FormEvent } from "react";

export function ChatInput({ disabled, onSend }: { disabled: boolean; onSend: (message: string) => void }) {
  const [value, setValue] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  return (
    <form className="chat-input-form" onSubmit={handleSubmit}>
      <div className="chat-input-row">
        <input
          placeholder={disabled ? "Resolve the pending action above first..." : "Type a message..."}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={disabled}
        />
        <button type="submit" disabled={disabled || !value.trim()}>
          Send
        </button>
      </div>
    </form>
  );
}
