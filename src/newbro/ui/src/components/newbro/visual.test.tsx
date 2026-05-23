import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DraftBrainPanel, RunnerBrainPanel } from "./visual";

const bro = {
  id: "hermes",
  name: "Hermes",
  role: "Runtime worker",
  source: "runtime" as const,
  status: "busy" as const,
  liveState: "live" as const,
  executorNodeId: null,
  nodeName: null,
  avatarType: "fox" as const,
  taskTitle: "Review console Home page",
  progress: 42,
  progressLabel: "42%",
  progressDetails: ["Comparing the current page against Linear."],
  idleNote: "Ready",
};

describe("Bro detail runtime panels", () => {
  it("renders the staged dispatch plan preview", () => {
    render(
      <DraftBrainPanel
        draftText="Review the console Home page and produce a proposal."
        dispatchPlan={{
          target_agent: "hermes",
          mode: "proposal_only",
          task_title: "Review console Home page",
          missing_context: [],
        }}
        canSend
        clearDisabled={false}
        sendDisabled={false}
        sending={false}
        clearing={false}
        onSend={vi.fn()}
        onClear={vi.fn()}
      />,
    );

    expect(screen.getByText("Dispatch plan")).toBeInTheDocument();
    expect(screen.getByText(/proposal_only/)).toBeInTheDocument();
    expect(screen.getByText(/Review console Home page/)).toBeInTheDocument();
  });

  it("renders agent timeline and artifact list from normalized events", () => {
    render(
      <RunnerBrainPanel
        bro={bro}
        summary={{
          task_id: "task-1",
          operational_summary: "Operational summary",
          conversational_summary: "Hermes is drafting a proposal.",
          latest_user_visible_status: "running",
          needs_user_input: false,
        }}
        taskRecords={[]}
        activeTaskId="task-1"
        stoppingTask={false}
        onStopTask={vi.fn()}
        agentEvents={[
          {
            event_id: "event-1",
            task_id: "task-1",
            agent_id: "hermes",
            type: "agent.progress",
            message: "Compared Home page against Linear.",
            importance: "low",
            delivery: "silent_ui",
            artifact_id: null,
            created_at: "2026-05-22T00:00:00Z",
          },
          {
            event_id: "event-2",
            task_id: "task-1",
            agent_id: "hermes",
            type: "artifact.ready",
            message: "Proposal is ready.",
            importance: "medium",
            delivery: "badge",
            artifact_id: "artifact-proposal",
            created_at: "2026-05-22T00:01:00Z",
          },
        ]}
      />,
    );

    expect(screen.getByText("Agent status timeline")).toBeInTheDocument();
    expect(screen.getByText("Compared Home page against Linear.")).toBeInTheDocument();
    expect(screen.getByText("Artifacts")).toBeInTheDocument();
    expect(screen.getByText("artifact-proposal")).toBeInTheDocument();
  });
});
