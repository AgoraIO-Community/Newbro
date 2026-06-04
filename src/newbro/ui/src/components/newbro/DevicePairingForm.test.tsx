import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DevicePairingForm } from "./DevicePairingForm";

describe("DevicePairingForm", () => {
  it("calls onClaim with the entered code and shows success", async () => {
    const onClaim = vi.fn().mockResolvedValue(undefined);
    render(<DevicePairingForm onClaim={onClaim} />);

    await userEvent.type(screen.getByLabelText(/device code/i), "7qf2");
    await userEvent.click(screen.getByRole("button", { name: /pair device/i }));

    expect(onClaim).toHaveBeenCalledWith("7QF2");
    expect(await screen.findByText(/device paired/i)).toBeInTheDocument();
  });

  it("shows an error message when onClaim rejects", async () => {
    const onClaim = vi.fn().mockRejectedValue(new Error("Invalid pairing code."));
    render(<DevicePairingForm onClaim={onClaim} />);

    await userEvent.type(screen.getByLabelText(/device code/i), "zzzz");
    await userEvent.click(screen.getByRole("button", { name: /pair device/i }));

    expect(await screen.findByText(/invalid pairing code/i)).toBeInTheDocument();
  });
});
