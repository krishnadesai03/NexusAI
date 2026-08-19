import type { TraceEvent } from "./types";

// One agent's column in the trace panel's side-by-side parallel-branch layout.
export interface TraceStep {
  tool: string;
  callDetail?: string;
  resultDetail?: string;
  status: "running" | "done";
}

export interface TraceBranch {
  agent: string;
  status: "running" | "done";
  steps: TraceStep[];
}

export interface Trace {
  reasoning?: string;
  branches: TraceBranch[];
  finished: boolean;
  error?: string;
}

export function emptyTrace(): Trace {
  return { branches: [], finished: false };
}

// Pure reducer, one TraceEvent at a time — chat/page.tsx calls this from streamChatMessage's
// onEvent callback as each event arrives, so the panel renders live rather than all at once
// after the request finishes.
export function applyTraceEvent(trace: Trace, event: TraceEvent): Trace {
  switch (event.type) {
    case "routing_decided":
      // Branch order here fixes the left-to-right column order in the panel — matches the order
      // Orchestrator.handle() actually fanned them out in, not an arbitrary/alphabetical one.
      return {
        ...trace,
        reasoning: event.reasoning,
        branches: event.agents.map((agent) => ({ agent, status: "running" as const, steps: [] })),
      };

    case "agent_started":
      if (trace.branches.some((b) => b.agent === event.agent)) return trace;
      return { ...trace, branches: [...trace.branches, { agent: event.agent, status: "running", steps: [] }] };

    case "agent_finished":
      return {
        ...trace,
        branches: trace.branches.map((b) => (b.agent === event.agent ? { ...b, status: "done" as const } : b)),
      };

    case "tool_called":
      return {
        ...trace,
        branches: trace.branches.map((b) =>
          b.agent === event.agent
            ? { ...b, steps: [...b.steps, { tool: event.tool, callDetail: event.detail, status: "running" as const }] }
            : b
        ),
      };

    case "tool_result":
      return {
        ...trace,
        branches: trace.branches.map((b) => {
          if (b.agent !== event.agent) return b;
          // A branch's own tool-calling loop is sequential (learnings.md #10) — there's never
          // more than one "running" step per branch, so the last one found is unambiguous.
          const steps = [...b.steps];
          for (let i = steps.length - 1; i >= 0; i--) {
            if (steps[i].tool === event.tool && steps[i].status === "running") {
              steps[i] = { ...steps[i], resultDetail: event.detail, status: "done" };
              break;
            }
          }
          return { ...b, steps };
        }),
      };

    case "done":
      return { ...trace, finished: true };

    case "error":
      return { ...trace, finished: true, error: event.error };

    default:
      return trace;
  }
}
