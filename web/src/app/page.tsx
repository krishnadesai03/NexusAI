"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, listDemoPersonas, selectDemoPersona } from "@/lib/api";
import type { DemoPersona } from "@/lib/types";

const PERSONA_DETAILS: Record<string, { initials: string; label: string; access: string[] }> = {
  employee: {
    initials: "SR",
    label: "Employee view",
    access: ["Company and Engineering knowledge", "Engineering performance data", "Safe employee directory and own profile"],
  },
  executive: {
    initials: "MD",
    label: "Executive view",
    access: ["Company-wide and executive knowledge", "Full Engineering performance data", "Full read-only business database"],
  },
};

export default function LandingPage() {
  const router = useRouter();
  const [personas, setPersonas] = useState<DemoPersona[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listDemoPersonas()
      .then(setPersonas)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "The demo service is unavailable. Please try again."))
      .finally(() => setLoading(false));
  }, []);

  async function continueAs(persona: DemoPersona) {
    setSelected(persona.slug);
    setError(null);
    try {
      await selectDemoPersona(persona.slug);
      router.push("/chat");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We could not start this demo session. Please try again.");
      setSelected(null);
    }
  }

  return (
    <main className="landing-page">
      <nav className="landing-nav" aria-label="Company">
        <div className="landing-brand-mark">A</div>
        <span>Alderbrook Systems</span>
        <span className="demo-pill">Interactive demo</span>
      </nav>
      <section className="landing-hero">
        <div className="landing-copy">
          <p className="eyebrow">Meet Nexus AI</p>
          <h1>One assistant.<br />The right access for every role.</h1>
          <p className="landing-intro">Explore a role-aware enterprise assistant that answers questions, analyzes internal data, remembers your conversation, and safely simulates workplace actions.</p>
          <div className="safety-note">
            <span aria-hidden="true">✓</span>
            <p><strong>Safe by design.</strong> Demo messages never reach real Slack or email accounts, and inactive data expires after 24 hours.</p>
          </div>
        </div>
        <div className="persona-section">
          <div className="persona-heading">
            <p className="eyebrow">Choose your perspective</p>
            <h2>Who would you like to explore as?</h2>
          </div>
          {error && <div className="landing-error" role="alert">{error}</div>}
          {loading && <div className="persona-loading">Loading demo profiles…</div>}
          <div className="persona-grid">
            {personas.map((persona) => {
              const details = PERSONA_DETAILS[persona.role] ?? {
                initials: persona.display_name.split(" ").map((part) => part[0]).join("").slice(0, 2),
                label: `${persona.role} view`,
                access: [],
              };
              const isSelected = selected === persona.slug;
              return (
                <article className={`persona-card persona-${persona.role}`} key={persona.slug}>
                  <div className="persona-card-top">
                    <div className="persona-avatar" aria-hidden="true">{details.initials}</div>
                    <span className="role-pill">{details.label}</span>
                  </div>
                  <h3>{persona.display_name}</h3>
                  <p className="persona-title">{persona.title}</p>
                  <p className="persona-department">{persona.department}</p>
                  <ul className="persona-access">{details.access.map((item) => <li key={item}>{item}</li>)}</ul>
                  <button className="persona-button" onClick={() => void continueAs(persona)} disabled={selected !== null}>
                    {isSelected ? "Opening workspace…" : `Continue as ${persona.display_name.split(" ")[0]}`}
                    {!isSelected && <span aria-hidden="true">→</span>}
                  </button>
                </article>
              );
            })}
          </div>
        </div>
      </section>
    </main>
  );
}
