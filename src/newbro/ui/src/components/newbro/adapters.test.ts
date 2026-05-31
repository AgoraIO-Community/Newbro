import { describe, expect, it } from "vitest";
import type { ExecutionDetailEntry, ExecutionRun } from "../../types";
import { buildReasoningStepsForTurn, latestReasoningLabel, buildReasoningStepsForNativeTurn } from "./adapters";
import type { BroTimelineTurn, NativeReasoningStep } from "../../types";

const entry = (id: string, ev: string, text: string): ExecutionDetailEntry => ({
  detail_id: id,
  task_id: "task-1",
  run_id: "run-1",
  execution_session_id: "es-1",
  event_type: ev,
  text,
  created_at: "2026-05-30T10:00:00Z",
});

const run: ExecutionRun = {
  run_id: "run-1",
  task_id: "task-1",
  execution_session_id: "es-1",
  executor_type: "codex",
  status: "running",
  claimed_by: null,
  run_revision: 0,
  latest_progress_message: null,
  output_summary: null,
  block_reason: null,
  failure_reason: null,
  metadata: {},
};

describe("buildReasoningStepsForTurn", () => {
  it("filters to PROGRESS and PLAN, marks newest active while run is RUNNING", () => {
    const details = [
      entry("a", "PROGRESS", "Looking up flights"),
      entry("b", "BLOCKED",  "Waiting for confirmation"),
      entry("c", "PLAN",     "Will compare three routes"),
      entry("d", "PROGRESS", "Comparing fares"),
    ];
    const steps = buildReasoningStepsForTurn(run, details);
    expect(steps.map((s) => s.id)).toEqual(["a", "c", "d"]);
    expect(steps.at(-1)!.status).toBe("active");
    expect(steps.slice(0, -1).every((s) => s.status === "done")).toBe(true);
  });

  it("marks all done when the run has terminated", () => {
    const completed: ExecutionRun = { ...run, status: "completed" };
    const details = [entry("a", "PROGRESS", "x"), entry("b", "PROGRESS", "y")];
    const steps = buildReasoningStepsForTurn(completed, details);
    expect(steps.every((s) => s.status === "done")).toBe(true);
  });

  it("returns [] for an empty details list", () => {
    expect(buildReasoningStepsForTurn(run, [])).toEqual([]);
  });
});

describe("latestReasoningLabel", () => {
  it("returns the most recent PROGRESS/PLAN text or null", () => {
    expect(latestReasoningLabel([])).toBeNull();
    expect(latestReasoningLabel([entry("a", "BLOCKED", "x")])).toBeNull();
    expect(latestReasoningLabel([
      entry("a", "PROGRESS", "first"),
      entry("b", "PROGRESS", "second"),
    ])).toBe("second");
  });
});

describe("buildReasoningStepsForNativeTurn", () => {
  const baseTurn = {
    turn_id: "thread-1:outbound:c1",
    thread_id: "thread-1",
    persona_id: "forge",
    executor_id: "codex",
    owner: "executor",
    client_request_id: "c1",
    executor_thread_id: "native-1",
    executor_turn_id: "turn-1",
    input_modality: "text",
    user: null,
    assistant: null,
    task: null,
    status: "running",
    created_at: null,
    updated_at: null,
    metadata: {},
  } as unknown as BroTimelineTurn;

  const steps: NativeReasoningStep[] = [
    { item_id: "i1", text: "step one", kind: "progress", created_at: "t1" },
    { item_id: "i2", text: "step two", kind: "progress", created_at: "t2" },
  ];
  const map = { "codex::native-1::turn-1": steps };

  it("marks the last step active while the turn is running", () => {
    const result = buildReasoningStepsForNativeTurn(baseTurn, map);
    expect(result.map((s) => s.label)).toEqual(["step one", "step two"]);
    expect(result[0].status).toBe("done");
    expect(result[1].status).toBe("active");
  });

  it("marks all steps done once the turn is completed", () => {
    const completed = { ...baseTurn, status: "completed" } as BroTimelineTurn;
    const result = buildReasoningStepsForNativeTurn(completed, map);
    expect(result.every((s) => s.status === "done")).toBe(true);
  });

  it("returns nothing for tracked-run turns or missing identity", () => {
    const tracked = { ...baseTurn, task: { task_id: "t1" } } as unknown as BroTimelineTurn;
    expect(buildReasoningStepsForNativeTurn(tracked, map)).toEqual([]);
    const noIds = { ...baseTurn, executor_turn_id: null } as BroTimelineTurn;
    expect(buildReasoningStepsForNativeTurn(noIds, map)).toEqual([]);
    expect(buildReasoningStepsForNativeTurn(baseTurn, {})).toEqual([]);
  });
});
