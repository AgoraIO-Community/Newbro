import { describe, expect, it } from "vitest";
import { buildTurnRenderModel } from "./turnRenderModel";
import type {
  BroTimelineMessage,
  BroTimelineTurn,
  ExecutionDetailEntry,
  ExecutionRun,
  NativeReasoningStep,
} from "../types";

const NATIVE_KEY = "codex::native-1::turn-1";

function nativeTurn(over: Partial<BroTimelineTurn> = {}): BroTimelineTurn {
  return {
    turn_id: "codex-import-1:codex:turn-1",
    thread_id: "codex-import-1",
    persona_id: "forge",
    executor_id: "codex",
    owner: "executor",
    client_request_id: null,
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
    ...over,
  } as unknown as BroTimelineTurn;
}

function assistant(text: string, itemId = "a1"): BroTimelineMessage {
  return {
    message_id: "m1",
    role: "assistant",
    kind: "text",
    text,
    created_at: "t3",
    status: "running",
    metadata: { codex_item_id: itemId },
  } as unknown as BroTimelineMessage;
}

const commentary: NativeReasoningStep[] = [
  { item_id: "c1", text: "Reading", kind: "progress", created_at: "t1" },
  { item_id: "c2", text: "Editing", kind: "progress", created_at: "t2" },
];

const noDeps = { executionRuns: [], recentExecutionDetails: {}, recentNativeTurnReasoning: {} };

describe("buildTurnRenderModel", () => {
  it("case 1 — refresh-reconstructed in-flight commentary renders as reasoning, never the answer, never shimmer", () => {
    const model = buildTurnRenderModel(nativeTurn({ status: "running", assistant: null }), null, {
      ...noDeps,
      recentNativeTurnReasoning: { [NATIVE_KEY]: commentary },
    });
    expect(model.liveState).toEqual({ kind: "live", sub: "reasoning" });
    expect(model.activeCommentary).toBe("Editing");
    expect(model.stepsForBubble.map((s) => s.id)).toEqual(["c1"]);
    expect(model.answerText).toBe("");
    expect(model.settledHasNothing).toBe(false);
  });

  it("case 2 — in-flight with a streaming answer: answering, no commentary line, all steps compact", () => {
    const model = buildTurnRenderModel(
      nativeTurn({ status: "running", assistant: assistant("Partial answer") }),
      null,
      { ...noDeps, recentNativeTurnReasoning: { [NATIVE_KEY]: commentary } },
    );
    expect(model.liveState).toEqual({ kind: "live", sub: "answering" });
    expect(model.activeCommentary).toBeNull();
    expect(model.answerText).toBe("Partial answer");
    expect(model.stepsForBubble.map((s) => s.id)).toEqual(["c1", "c2"]);
  });

  it("case 3 — refresh after completion: settled answer with commentary as collapsed steps", () => {
    const settledSteps: NativeReasoningStep[] = [
      { item_id: "c1", text: "Working", kind: "progress", created_at: "t1" },
      { item_id: "a1", text: "Final answer", kind: "progress", created_at: "t2" },
    ];
    const model = buildTurnRenderModel(
      nativeTurn({ status: "completed", assistant: assistant("Final answer", "a1") }),
      null,
      { ...noDeps, recentNativeTurnReasoning: { [NATIVE_KEY]: settledSteps } },
    );
    expect(model.liveState).toEqual({ kind: "settled" });
    expect(model.answerText).toBe("Final answer");
    expect(model.stepsForBubble.map((s) => s.id)).toEqual(["c1"]);
    expect(model.settledHasNothing).toBe(false);
  });

  it("case 4 — settled with nothing renders nothing", () => {
    const model = buildTurnRenderModel(nativeTurn({ status: "completed", assistant: null }), null, noDeps);
    expect(model.liveState).toEqual({ kind: "settled" });
    expect(model.settledHasNothing).toBe(true);
  });

  it("case 5 — in-flight with no reasoning yet is connecting (the pre-seed shimmer state)", () => {
    const model = buildTurnRenderModel(nativeTurn({ status: "running", assistant: null }), null, noDeps);
    expect(model.liveState).toEqual({ kind: "live", sub: "connecting" });
    expect(model.activeCommentary).toBeNull();
    expect(model.stepsForBubble).toEqual([]);
    expect(model.settledHasNothing).toBe(false);
  });

  it("case 6 — a task-based turn draws reasoning from execution-run details, not native", () => {
    const run: ExecutionRun = {
      run_id: "r1",
      task_id: "task-1",
      execution_session_id: "es1",
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
    const detail: ExecutionDetailEntry = {
      detail_id: "d1",
      task_id: "task-1",
      run_id: "r1",
      execution_session_id: "es1",
      event_type: "PROGRESS",
      text: "Compiling",
      created_at: "t1",
    };
    const turn = nativeTurn({ status: "running", task: { task_id: "task-1" } as unknown as BroTimelineTurn["task"] });
    const model = buildTurnRenderModel(turn, null, {
      executionRuns: [run],
      recentExecutionDetails: { "task-1": [detail] },
      recentNativeTurnReasoning: { [NATIVE_KEY]: commentary },
    });
    expect(model.liveState).toEqual({ kind: "live", sub: "reasoning" });
    expect(model.activeCommentary).toBe("Compiling");
    expect(model.stepsForBubble).toEqual([]);
  });

  it("case 7 — canStop is true while live with a task, false once settled", () => {
    const live = buildTurnRenderModel(
      nativeTurn({ status: "running", task: { task_id: "task-1" } as unknown as BroTimelineTurn["task"] }),
      null,
      { ...noDeps, recentNativeTurnReasoning: { [NATIVE_KEY]: commentary } },
    );
    expect(live.canStop).toBe(true);
    expect(live.stopTaskId).toBe("task-1");

    const settled = buildTurnRenderModel(
      nativeTurn({ status: "completed", task: { task_id: "task-1" } as unknown as BroTimelineTurn["task"] }),
      null,
      noDeps,
    );
    expect(settled.canStop).toBe(false);
  });
});
