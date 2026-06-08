import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { filterSkills, DesktopSkillMenu } from "./SkillPicker";
import type { ExecutorSkill } from "../../types";

const SKILLS: ExecutorSkill[] = [
  { name: "doc", display_name: "Word Docs", description: "Edit docx", hint: null, path: "/a", enabled: true },
  { name: "flight-search", display_name: "Flight search", description: "Compare fares", hint: null, path: "/b", enabled: true },
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
