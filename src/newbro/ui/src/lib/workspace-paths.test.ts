import { describe, it, expect } from "vitest";
import { extractPathTokens, isUnderWorkspace, basename } from "./workspace-paths";

describe("extractPathTokens", () => {
  it("extracts an absolute path with trailing punctuation", () => {
    expect(extractPathTokens("saved to /work/out/report.pdf.")).toEqual(["/work/out/report.pdf"]);
  });
  it("strips backticks, quotes, and parens", () => {
    expect(extractPathTokens("see `/work/a.txt`")).toEqual(["/work/a.txt"]);
    expect(extractPathTokens('see "/work/a.txt"')).toEqual(["/work/a.txt"]);
    expect(extractPathTokens("(see /work/a.txt)")).toEqual(["/work/a.txt"]);
  });
  it("ignores relative paths and prose", () => {
    expect(extractPathTokens("out/report.pdf and hello world")).toEqual([]);
  });
  it("dedupes", () => {
    expect(extractPathTokens("/a /a /b")).toEqual(["/a", "/b"]);
  });
  it("keeps passwd and passwd.txt distinct", () => {
    expect(extractPathTokens("/etc/passwd.txt")).toEqual(["/etc/passwd.txt"]);
  });
});

describe("isUnderWorkspace", () => {
  it("matches inside the root, rejects outside", () => {
    expect(isUnderWorkspace("/work/a.txt", "/work")).toBe(true);
    expect(isUnderWorkspace("/work", "/work")).toBe(true);
    expect(isUnderWorkspace("/works/a.txt", "/work")).toBe(false);
    expect(isUnderWorkspace("/etc/passwd", "/work")).toBe(false);
  });
});

describe("basename", () => {
  it("returns the last segment", () => {
    expect(basename("/work/out/report.pdf")).toBe("report.pdf");
  });
});
