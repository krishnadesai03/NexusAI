"use client";

import { useEffect, useRef, type SubmitEvent } from "react";

export function ChatInput({
  disabled,
  value,
  onValueChange,
  onSend,
}: {
  disabled: boolean;
  value: string;
  onValueChange: (value: string) => void;
  onSend: (message: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (value && !disabled) inputRef.current?.focus();
  }, [disabled, value]);

  function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    onValueChange("");
  }

  return (
    <form className="chat-input-form" onSubmit={handleSubmit}>
      <div className="chat-input-row">
        <input
          ref={inputRef}
          placeholder={disabled ? "Resolve the pending action above first..." : "Type a message..."}
          value={value}
          onChange={(e) => onValueChange(e.target.value)}
          disabled={disabled}
        />
        <button type="submit" disabled={disabled || !value.trim()}>
          Send
        </button>
      </div>
    </form>
  );
}
