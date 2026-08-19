"use client";

import { useState, type SubmitEvent } from "react";
import { useRouter } from "next/navigation";
import { ApiError, login, setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { token } = await login(email, password);
      setToken(token);
      router.push("/chat");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-left">
        <p className="login-brand">Alderbrook Systems</p>
        <h1 className="login-welcome">
          Welcome
          <br />
          Back
        </h1>
        <p className="login-subtitle">Simply all the tools my team and I need.</p>
      </div>

      <div className="login-right">
        <h2 className="login-title">Sign in</h2>

        {error && <div className="error-text">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="email">Email Address</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <button type="submit" className="primary-button" disabled={submitting}>
            {submitting ? "Signing in..." : "Sign in now"}
          </button>
        </form>
      </div>
    </div>
  );
}
