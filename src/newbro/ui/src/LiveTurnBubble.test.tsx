import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { LiveTurnBubble } from "./LiveTurnBubble";

const steps = [{ id: "s1", label: "Reading the repo" }, { id: "s2", label: "Drafting a plan" }];

describe("LiveTurnBubble", () => {
  it("connecting renders the shimmer skeleton + alive orb and no steps", () => {
    const { container } = render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "live", sub: "connecting" }} steps={[]} answer="" mobile={false} canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".dt-reason-skeleton")).not.toBeNull();
    expect(container.querySelector(".dt-reason-orb")).not.toBeNull();
    expect(container.querySelector(".dt-reason-steps")).toBeNull();
    expect(screen.getByText(/Atlas is working/)).toBeTruthy();
  });

  it("reasoning renders the step list, progress shimmer, and alive orb", () => {
    const { container } = render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "live", sub: "reasoning" }} steps={steps} answer="" mobile={false} canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".dt-reason-skeleton")).toBeNull();
    expect(container.querySelectorAll(".dt-reason-step").length).toBe(2);
    expect(container.querySelector(".dt-reason-stream-progress")).not.toBeNull();
    expect(container.querySelector(".dt-reason-orb")).not.toBeNull();
  });

  it("reasoning streams the commentary prominently with a caret, above compact steps", () => {
    const { container } = render(
      <LiveTurnBubble
        broName="Atlas"
        state={{ kind: "live", sub: "reasoning" }}
        steps={steps}
        activeCommentary="Looking through the devx docs"
        answer=""
        mobile={false}
        canStop={false}
        onStop={() => {}}
      />,
    );
    // The streaming commentary is a prominent line with a caret (not the shimmer).
    expect(container.querySelector(".dt-commentary-text")?.textContent).toBe("Looking through the devx docs");
    expect(container.querySelector(".dt-reason-caret")).not.toBeNull();
    expect(container.querySelector(".dt-reason-stream-progress")).toBeNull();
    // The completed steps render compactly and do NOT duplicate the live commentary.
    expect(container.querySelectorAll(".dt-reason-step").length).toBe(2);
    const stepTexts = Array.from(container.querySelectorAll(".dt-reason-step-text")).map((n) => n.textContent);
    expect(stepTexts).not.toContain("Looking through the devx docs");
  });

  it("answering streams the answer while keeping steps, the alive orb, and a caret", () => {
    const { container } = render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "live", sub: "answering" }} steps={steps} answer="Here is the answer" mobile={false} canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".dt-reason-orb")).not.toBeNull();
    expect(container.querySelector(".dt-reason-caret")).not.toBeNull();
    expect(container.querySelectorAll(".dt-reason-step").length).toBe(2);
    expect(screen.getByText(/Here is the answer/)).toBeTruthy();
  });

  it("settled shows the answer with no alive cue, no header, no Stop", () => {
    const { container } = render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "settled" }} steps={steps} answer="Final answer" mobile={false} canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".dt-reason-orb")).toBeNull();
    expect(container.querySelector(".dt-reason-caret")).toBeNull();
    expect(screen.queryByText(/Atlas is working/)).toBeNull();
    expect(screen.getByText(/Final answer/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /stop/i })).toBeNull();
  });

  it("settled offers a Show all toggle when there are more than 3 steps", () => {
    const many = [1, 2, 3, 4, 5].map((n) => ({ id: `s${n}`, label: `Step ${n}` }));
    render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "settled" }} steps={many} answer="Done" mobile={false} canStop={false} onStop={() => {}} />,
    );
    const toggle = screen.getByRole("button", { name: /show all 5 steps/i });
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: /hide steps/i })).toBeTruthy();
  });

  it("uses thr- classes on mobile", () => {
    const { container } = render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "live", sub: "reasoning" }} steps={steps} answer="" mobile canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".thr-reason")).not.toBeNull();
    expect(container.querySelectorAll(".thr-reason-step").length).toBe(2);
  });

  it("shows Stop while live and fires onStop; hidden when !canStop", () => {
    const onStop = vi.fn();
    const { rerender } = render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "live", sub: "reasoning" }} steps={steps} answer="" mobile={false} canStop onStop={onStop} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /stop/i }));
    expect(onStop).toHaveBeenCalledTimes(1);
    rerender(
      <LiveTurnBubble broName="Atlas" state={{ kind: "live", sub: "reasoning" }} steps={steps} answer="" mobile={false} canStop={false} onStop={onStop} />,
    );
    expect(screen.queryByRole("button", { name: /stop/i })).toBeNull();
  });

  it("keeps the same answer DOM node across the answering→settled transition", () => {
    const { container, rerender } = render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "live", sub: "answering" }} steps={steps} answer="Streaming answer" mobile={false} canStop={false} onStop={() => {}} />,
    );
    const before = container.querySelector(".dt-answer-text");
    expect(before).not.toBeNull();
    rerender(
      <LiveTurnBubble broName="Atlas" state={{ kind: "settled" }} steps={steps} answer="Streaming answer" mobile={false} canStop={false} onStop={() => {}} />,
    );
    const after = container.querySelector(".dt-answer-text");
    expect(after).toBe(before);
  });
});
