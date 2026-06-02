import { describe, it, expect } from "vitest";
import { remark } from "remark";
import { remarkWorkspacePaths, DOWNLOAD_SCHEME } from "./workspace-file-link";

function transform(md: string, workspaceRoot: string): string {
  const processor = remark().use(remarkWorkspacePaths, { workspaceRoot });
  const tree = processor.parse(md);
  processor.runSync(tree);
  return JSON.stringify(tree);
}

describe("remarkWorkspacePaths", () => {
  it("wraps an in-workspace path in a download link node", () => {
    const json = transform("saved to /work/report.pdf here", "/work");
    expect(json).toContain(`${DOWNLOAD_SCHEME}/work/report.pdf`);
  });
  it("leaves out-of-workspace paths untouched", () => {
    const json = transform("see /etc/passwd now", "/work");
    expect(json).not.toContain(DOWNLOAD_SCHEME);
  });
});
