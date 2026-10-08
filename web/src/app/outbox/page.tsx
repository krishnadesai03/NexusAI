"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, clearSession, getToken, listDemoOutbox, me } from "@/lib/api";
import type { DemoDelivery, MeResponse } from "@/lib/types";

export default function OutboxPage() {
  const router = useRouter();
  const [profile, setProfile] = useState<MeResponse | null>(null);
  const [deliveries, setDeliveries] = useState<DemoDelivery[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/");
      return;
    }
    Promise.all([me(), listDemoOutbox()])
      .then(([user, items]) => {
        setProfile(user);
        setDeliveries(items);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Could not load the Demo Outbox.");
      })
      .finally(() => setLoading(false));
  }, [router]);

  function switchProfile() {
    clearSession();
    router.push("/");
  }

  return (
    <main className="outbox-page">
      <header className="outbox-header">
        <div className="brand"><span className="brand-logo">N</span><div><h1>Demo Outbox</h1><p>Nexus AI · Alderbrook Systems</p></div></div>
        <div className="outbox-nav">
          <Link className="secondary-link" href="/chat">← Back to chat</Link>
          <button className="text-button" onClick={switchProfile}>Switch profile</button>
        </div>
      </header>

      <section className="outbox-content">
        <div className="outbox-title-row">
          <div>
            <p className="eyebrow">Safe delivery preview</p>
            <h2>Messages captured, not delivered</h2>
            <p>Every confirmed Slack message or email appears here so you can inspect the result without contacting a real person.</p>
          </div>
          {profile && <div className="outbox-profile"><span>Viewing as</span><strong>{profile.display_name}</strong><small>{profile.title}</small></div>}
        </div>

        {error && <div className="outbox-error" role="alert">{error}</div>}
        {loading && <div className="outbox-empty">Loading captured messages…</div>}
        {!loading && !error && deliveries.length === 0 && (
          <div className="outbox-empty">
            <div className="outbox-empty-icon">↗</div>
            <h3>No simulated messages yet</h3>
            <p>Ask Nexus AI to draft a Slack message or email, then confirm it. The captured message will appear here.</p>
            <Link className="outbox-primary-link" href="/chat">Return to chat</Link>
          </div>
        )}

        <div className="delivery-list">
          {deliveries.map((delivery) => (
            <article className="delivery-card" key={delivery.id}>
              <div className="delivery-meta">
                <span className={`channel-badge channel-${delivery.channel}`}>{delivery.channel === "slack" ? "Slack" : "Email"}</span>
                <span className="captured-badge">✓ Captured safely</span>
                <time dateTime={delivery.created_at}>{formatDate(delivery.created_at)}</time>
              </div>
              <div className="delivery-recipient"><span>To</span><strong>{delivery.recipient}</strong></div>
              {delivery.subject && <div className="delivery-subject"><span>Subject</span><strong>{delivery.subject}</strong></div>}
              <div className="delivery-content">{delivery.content}</div>
              <p className="delivery-footnote">No external message was sent. This preview expires with the demo session.</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
