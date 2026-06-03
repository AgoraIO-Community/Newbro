import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarkdownText } from "./markdown-text";

describe("MarkdownText download control", () => {
  const ctx = {
    sessionId: "s1",
    threadId: "t1",
    turnId: "turn-1",
    workspaceRoot: "/work",
  };

  it("renders a download control for an in-workspace path", () => {
    render(<MarkdownText downloadContext={ctx}>{"saved to /work/report.pdf"}</MarkdownText>);
    const link = screen.getByTestId("workspace-file-download");
    expect(link).toHaveTextContent("report.pdf");
    expect(link.getAttribute("href")).toContain("/sessions/s1/bro-threads/t1/turns/turn-1/file");
    expect(link.getAttribute("href")).toContain("path=%2Fwork%2Freport.pdf");
  });

  it("renders a download control for an in-workspace markdown link (the common assistant form)", () => {
    render(
      <MarkdownText downloadContext={ctx}>
        {"Created the report here:\n\n[report.md](/work/out/report.md)"}
      </MarkdownText>,
    );
    const link = screen.getByTestId("workspace-file-download");
    expect(link.getAttribute("href")).toContain("/sessions/s1/bro-threads/t1/turns/turn-1/file");
    expect(link.getAttribute("href")).toContain("path=%2Fwork%2Fout%2Freport.md");
  });

  it("leaves an out-of-workspace markdown link as a normal link", () => {
    render(<MarkdownText downloadContext={ctx}>{"[passwd](/etc/passwd)"}</MarkdownText>);
    expect(screen.queryByTestId("workspace-file-download")).toBeNull();
  });

  it("leaves out-of-workspace paths as plain text", () => {
    render(<MarkdownText downloadContext={ctx}>{"see /etc/passwd"}</MarkdownText>);
    expect(screen.queryByTestId("workspace-file-download")).toBeNull();
  });

  it("renders plain text when no downloadContext is provided", () => {
    render(<MarkdownText>{"saved to /work/report.pdf"}</MarkdownText>);
    expect(screen.queryByTestId("workspace-file-download")).toBeNull();
  });
});
