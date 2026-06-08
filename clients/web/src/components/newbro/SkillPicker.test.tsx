import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { filterSkills, DesktopSkillMenu, MobileSkillSheet, SkillLeadCluster } from "./SkillPicker";
import type { ExecutorSkill } from "../../types";

const SKILLS: ExecutorSkill[] = [
  { name: "doc", display_name: "Word Docs", description: "Edit docx", hint: null, path: "/a", enabled: true },
  { name: "flight-search", display_name: "Flight search", description: "Compare fares", hint: null, path: "/b", enabled: true },
];

const WITH_DISABLED: ExecutorSkill[] = [
  ...SKILLS,
  { name: "stays", display_name: "Find stays", description: "Rank hotels", hint: null, path: "/c", enabled: false },
];

describe("filterSkills", () => {
  it("filters by name and description, case-insensitive", () => {
    expect(filterSkills(SKILLS, "flight").map((s) => s.name)).toEqual(["flight-search"]);
    expect(filterSkills(SKILLS, "").length).toBe(2);
    expect(filterSkills(SKILLS, "fares").map((s) => s.name)).toEqual(["flight-search"]);
  });
});

describe("DesktopSkillMenu", () => {
  it("renders rows and fires onChoose", () => {
    const onChoose = vi.fn();
    render(<DesktopSkillMenu skills={SKILLS} query="" selected={null} broName="Atlas" onChoose={onChoose} onClose={() => {}} />);
    fireEvent.click(screen.getByText("Word Docs"));
    expect(onChoose).toHaveBeenCalledWith(SKILLS[0]);
  });

  it("shows empty state when no match", () => {
    render(<DesktopSkillMenu skills={SKILLS} query="zzz" selected={null} broName="Atlas" onChoose={() => {}} onClose={() => {}} />);
    expect(screen.getByText(/No skill matches/i)).toBeInTheDocument();
  });
});

describe("SkillLeadCluster", () => {
  it("shows the Skill chip when nothing is selected and opens the popover on click", () => {
    render(<SkillLeadCluster skills={SKILLS} selected={null} broName="Atlas" onChoose={() => {}} onClear={() => {}} />);
    // Popover closed initially: no row visible.
    expect(screen.queryByText("Word Docs")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle(/Run this turn with a skill/i));
    expect(screen.getByText("Word Docs")).toBeInTheDocument();
  });

  it("calls onChoose when a row is picked from the open popover", () => {
    const onChoose = vi.fn();
    render(<SkillLeadCluster skills={SKILLS} selected={null} broName="Atlas" onChoose={onChoose} onClear={() => {}} />);
    fireEvent.click(screen.getByTitle(/Run this turn with a skill/i));
    fireEvent.click(screen.getByText("Flight search"));
    expect(onChoose).toHaveBeenCalledWith(SKILLS[1]);
  });

  it("closes the popover on Escape", () => {
    render(<SkillLeadCluster skills={SKILLS} selected={null} broName="Atlas" onChoose={() => {}} onClear={() => {}} />);
    fireEvent.click(screen.getByTitle(/Run this turn with a skill/i));
    expect(screen.getByText("Word Docs")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("Word Docs")).not.toBeInTheDocument();
  });

  it("shows the selected pill and clears via the remove button", () => {
    const onClear = vi.fn();
    render(<SkillLeadCluster skills={SKILLS} selected={SKILLS[0]} broName="Atlas" onChoose={() => {}} onClear={onClear} />);
    expect(screen.getByText("Word Docs")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Remove Word Docs skill/i }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("renders nothing when disabled", () => {
    const { container } = render(
      <SkillLeadCluster skills={SKILLS} selected={null} broName="Atlas" disabled onChoose={() => {}} onClear={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("MobileSkillSheet", () => {
  it("renders rows when open and fires onChoose", () => {
    const onChoose = vi.fn();
    render(
      <MobileSkillSheet open skills={SKILLS} query="" selected={null} broName="Atlas" onChoose={onChoose} onClose={() => {}} />,
    );
    fireEvent.click(screen.getByText("Word Docs"));
    expect(onChoose).toHaveBeenCalledWith(SKILLS[0]);
  });

  it("renders a disabled skill that cannot be chosen", () => {
    const onChoose = vi.fn();
    render(
      <MobileSkillSheet open skills={WITH_DISABLED} query="" selected={null} broName="Atlas" onChoose={onChoose} onClose={() => {}} />,
    );
    const disabledRow = screen.getByText("Find stays").closest("button") as HTMLButtonElement;
    expect(disabledRow).toBeDisabled();
    fireEvent.click(disabledRow);
    expect(onChoose).not.toHaveBeenCalled();
  });
});
