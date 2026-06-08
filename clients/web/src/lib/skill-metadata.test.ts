import { describe, it, expect } from "vitest";
import { skillFromMessageMetadata } from "./skill-metadata";

describe("skillFromMessageMetadata", () => {
  it("reads { name, display_name } from a well-formed skill object", () => {
    const result = skillFromMessageMetadata({ skill: { name: "doc", display_name: "Word Docs" } });
    expect(result).toEqual({ name: "doc", display_name: "Word Docs" });
  });

  it("falls back display_name to name when display_name is missing", () => {
    const result = skillFromMessageMetadata({ skill: { name: "doc" } });
    expect(result).toEqual({ name: "doc", display_name: "doc" });
  });

  it("returns null for empty metadata object {}", () => {
    expect(skillFromMessageMetadata({})).toBeNull();
  });

  it("returns null when skill is a non-object (string)", () => {
    expect(skillFromMessageMetadata({ skill: "doc" })).toBeNull();
  });

  it("returns null when skill is a non-object (number)", () => {
    expect(skillFromMessageMetadata({ skill: 42 })).toBeNull();
  });

  it("returns null when skill is an array", () => {
    expect(skillFromMessageMetadata({ skill: ["doc"] })).toBeNull();
  });

  it("returns null when metadata is undefined", () => {
    expect(skillFromMessageMetadata(undefined)).toBeNull();
  });

  it("returns null when skill object has no name field", () => {
    expect(skillFromMessageMetadata({ skill: { display_name: "Word Docs" } })).toBeNull();
  });
});
