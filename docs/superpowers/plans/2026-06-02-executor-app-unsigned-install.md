# Unsigned Executor App Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the unsigned `Newbro Executor.app` run on other Macs with only a one-time GUI approval (no `xattr`, no notarization), by ad-hoc sealing the bundle and documenting the first-launch approval.

**Architecture:** Two changes — add a `codesign --force --deep --sign -` ad-hoc seal to `macos/package-app.sh` (so the bundle gets the overridable "unverified developer" dialog instead of an unfixable "app is damaged" error), and add an "Installing on another Mac" section to `macos/README.md` covering the macOS-version-specific approval flow. No code, no tests (build-script + docs); verification is `codesign --verify` and a successful packaging run.

**Tech Stack:** bash, `codesign` (ad-hoc), macOS Gatekeeper, Markdown.

---

### Task 1: Ad-hoc seal the app bundle in package-app.sh

**Files:**
- Modify: `macos/package-app.sh` (after the Info.plist heredoc, before the final `echo`)

- [ ] **Step 1: Add the ad-hoc codesign step**

In `macos/package-app.sh`, the file currently ends with:

```bash
</dict>
</plist>
PLIST

echo "[package-app] done: $APP"
```

Insert a codesign step between the `PLIST` heredoc terminator and the final
`echo`, so the block becomes:

```bash
</dict>
</plist>
PLIST

# Ad-hoc seal the whole bundle (Info.plist + binary). `--sign -` needs no
# certificate or Apple account; it is NOT notarization. It ensures a downloaded
# copy shows the overridable "unverified developer" dialog rather than an
# "app is damaged" error that cannot be cleared via "Open Anyway".
echo "[package-app] ad-hoc signing bundle"
codesign --force --deep --sign - "$APP"

echo "[package-app] done: $APP"
```

- [ ] **Step 2: Rebuild the bundle and verify the signature**

Run:
```bash
./macos/package-app.sh 2>&1 | tail -3
codesign --verify --deep --strict --verbose=2 "macos/dist/Newbro Executor.app" && echo "VERIFY-OK"
codesign -dv --verbose=2 "macos/dist/Newbro Executor.app" 2>&1 | grep -iE "Signature|flags"
```
Expected: packaging ends with `[package-app] done: …`; `VERIFY-OK` prints (no
verification errors); the signature line shows `Signature=adhoc`.

- [ ] **Step 3: Confirm it still launches locally and Swift tests pass**

Run:
```bash
swift test --package-path macos 2>&1 | grep -E "Executed [0-9]+ tests" | tail -1
```
Expected: the Swift suite still passes (the build-script edit doesn't touch code, but confirm the package still builds). Do NOT launch the GUI from the agent session.

- [ ] **Step 4: Commit**

```bash
git add macos/package-app.sh
git commit -m "build(macos): ad-hoc seal the app bundle for cleaner Gatekeeper override"
```

---

### Task 2: Document installing on another Mac

**Files:**
- Modify: `macos/README.md` (append a new section)

- [ ] **Step 1: Append the "Installing on another Mac" section**

Add this section to the end of `macos/README.md` (keep existing content):

```markdown
## Installing on another Mac (unsigned build)

The app is ad-hoc signed but not notarized (no paid Apple Developer account), so
the **first** launch on a Mac other than the build machine needs a one-time
approval. No terminal or `xattr` is required.

1. **Build and share (you):**
   ```bash
   ./macos/package-app.sh
   ```
   Then compress `macos/dist/Newbro Executor.app` (Finder → Compress, or
   `ditto -c -k --keepParent "macos/dist/Newbro Executor.app" NewbroExecutor.zip`)
   and send it (AirDrop, download, etc.).

2. **Recipient:** unzip it, and optionally drag `Newbro Executor.app` to
   `/Applications`.

3. **First launch — one-time approval.** Double-click the app. If macOS blocks it
   ("can't verify the developer"):
   - **macOS 14 (Sonoma) or earlier:** Control-click (right-click) the app icon →
     **Open** → **Open** in the dialog.
   - **macOS 15 (Sequoia) or later:** open **System Settings → Privacy &
     Security**, scroll to **Security**, find the message
     "*Newbro Executor* was blocked…" → click **Open Anyway** → confirm and
     authenticate (Touch ID / password).

4. After approving once, the app opens normally every time — no terminal, no
   `xattr`.

This step exists only because the app isn't notarized; it is a one-time,
per-machine action.
```

- [ ] **Step 2: Verify the README renders with both branches**

Run:
```bash
grep -nE "Installing on another Mac|Sonoma\) or earlier|Sequoia\) or later|Open Anyway" macos/README.md
```
Expected: all four anchors are present (the section heading, both macOS-version
branches, and the "Open Anyway" instruction).

- [ ] **Step 3: Commit**

```bash
git add macos/README.md
git commit -m "docs(macos): document one-time approval for installing on other Macs"
```

---

## Self-Review

**Spec coverage:**
- Ad-hoc bundle seal in `package-app.sh` → Task 1.
- README "Installing on another Mac" section with both macOS-version approval
  flows → Task 2.
- Verification (`codesign --verify`, packaging succeeds, README anchors) →
  Task 1 Step 2–3, Task 2 Step 2.
- Non-goals (no notarization, no curl installer) → respected; nothing in either
  task adds them.

**Placeholder scan:** none — both tasks contain the exact bash/markdown to add
and exact verification commands.

**Consistency:** `$APP` is the existing variable in `package-app.sh`; the
codesign line uses it. The README version branches (Sonoma-or-earlier vs
Sequoia-or-later) match the spec exactly.
