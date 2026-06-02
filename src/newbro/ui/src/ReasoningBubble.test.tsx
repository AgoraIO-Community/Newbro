import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ReasoningBubble } from "./ReasoningBubble";

const steps = [{ id: "s1", label: "Reading the repo" }, { id: "s2", label: "Drafting a plan" }];

describe("ReasoningBubble", () => {
  it("ack renders the shimmer skeleton and no step list", () => {
    const { container } = render(
      <ReasoningBubble broName="Atlas" phase="ack" steps={[]} mobile={false} canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".dt-reason-skeleton")).not.toBeNull();
    expect(container.querySelector(".dt-reason-steps")).toBeNull();
    expect(screen.getByText(/Atlas is working/)).toBeTruthy();
  });

  it("streaming renders the windowed step list and no skeleton", () => {
    const { container } = render(
      <ReasoningBubble broName="Atlas" phase="streaming" steps={steps} mobile={false} canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".dt-reason-skeleton")).toBeNull();
    expect(container.querySelectorAll(".dt-reason-step").length).toBe(2);
  });

  it("uses thr- classes on mobile", () => {
    const { container } = render(
      <ReasoningBubble broName="Atlas" phase="ack" steps={[]} mobile canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".thr-reason-skeleton")).not.toBeNull();
  });

  it("shows Stop when canStop and fires onStop on click; hidden when !canStop", () => {
    const onStop = vi.fn();
    const { rerender } = render(
      <ReasoningBubble broName="Atlas" phase="streaming" steps={steps} mobile={false} canStop onStop={onStop} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /stop/i }));
    expect(onStop).toHaveBeenCalledTimes(1);
    rerender(
      <ReasoningBubble broName="Atlas" phase="streaming" steps={steps} mobile={false} canStop={false} onStop={onStop} />,
    );
    expect(screen.queryByRole("button", { name: /stop/i })).toBeNull();
  });
});
