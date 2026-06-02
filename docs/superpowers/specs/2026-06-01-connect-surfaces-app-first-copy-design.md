# Connect Surfaces: App-First Copy & Instructions — Design

Date: 2026-06-01
Status: Approved (design)

## Goal

The macOS Newbro Executor app now installs the runtime, supervises
`newbro executor run`, auto-updates the CLI, and accepts a connect command via
its "Paste connect command…" menu item. But the web UI's connect surfaces still
instruct users to run raw terminal/CLI commands (`curl … install.sh`,
`newbro executor run …`). Update the **text and instructions** across the three
connect surfaces to make the macOS app the recommended path, while keeping the
terminal commands available as a fallback for non-Mac (Linux/headless)
executors.

This is a copy/instructions change plus one new download button/link and one
shared URL constant. No command-builder logic changes.

## Current state (all in `src/newbro/ui/src/ArtboardShell.tsx`)

- **Home "Add a bro" tile** (`AddBroTile`, ~line 3710): sub-label "Generates an
  install/connect command".
- **New-bro creation modal — "STEP 3 · CONNECT A COMPUTER"** (~lines 2145-2200):
  - Guide: "On the computer where {bro} should work, paste this in a terminal to
    install newbro:" → install command box (`commands.installOnly`,
    fallback `curl -fsSL newbro.dev/install.sh | sh`).
  - Guide 2: "Then start it with your one-time key — we filled in the details for
    you:" → run command box (`commands.runOnly`,
    fallback `newbro executor run --token pending`).
  - Status spinner copy, eyebrow-meta ("installs CLI + starts the executor"),
    footer ("Install/connect command will be generated on demand"), and a TIP
    about "any computer that stays on — your Mac, a spare laptop, a mini in the
    closet."
- **Bro-detail offline header** (`NodeOfflineNotice` / `OfflineCommandLine`,
  ~lines 2316-2435):
  - Desktop: masked `newbro executor run --token ••••••` (copy `runOnly`); foot
    "Run on {node} to bring it back — it already has the CLI installed." plus a
    "Reinstall or update the CLI" disclosure revealing `commands.installConnect`
    (`curl … install.sh`).
  - Mobile: body line "Copy or share Install + connect from desktop, then run it
    in Terminal on the computer that should work for this bro."

The connect command (`runOnly` =
`newbro executor run --base-url … --node-id … --token … --enabled-executor codex`)
is exactly the format `macos/Sources/NewbroExecutorCore/ConnectCommand.swift`
`parseConnectCommand` accepts. So the command does not change — only where the
user pastes it.

## Decisions (from brainstorm)

- **Positioning:** app-first; terminal commands demoted behind an "Advanced /
  not on a Mac" disclosure, kept for Linux/headless executors.
- **Download target:** the GitHub Releases page,
  `https://github.com/AgoraIO/Synopse/releases/latest` (CI publishes the DMGs
  there).
- **Handoff:** copy the connect command → paste into the app's "Paste connect
  command…". No new deep-link / URL-scheme feature (explicitly out of scope).

## Changes

### 0. Shared

- Add a module-level constant near the other connect helpers in
  `ArtboardShell.tsx` (or a small `lib` constant if one fits the existing
  pattern):
  `const APP_DOWNLOAD_URL = "https://github.com/AgoraIO/Synopse/releases/latest";`
- The command builders in `lib/session-client.ts`
  (`buildExecutorConnectCommands`, `installOnly`, `installConnect`, `runOnly`)
  are unchanged.

### 1. New-bro creation — "STEP 3 · CONNECT A COMPUTER"

Restructure the step from two terminal commands to app-first:

- **A — Install (replaces the install command box):**
  - Guide: "On the Mac where **{bro}** should work, install the Newbro app:"
  - A **"Download the Newbro app"** button/link → `APP_DOWNLOAD_URL` (opens in a
    new tab). Reuse existing button styling; no new command box for install.
- **B — Connect (keeps the run command box):**
  - Guide: "Then copy this connect command and paste it into the app (menu →
    **Paste connect command**):"
  - Keep the `commands.runOnly` box + Copy button and the status spinner. Status
    trailing line → "…once {bro} connects. Nothing else on that Mac changes."
    (existing "Waiting to hear from your computer…" strong line unchanged).
- **Advanced disclosure (collapsed by default):** a small toggle
  "Not on a Mac? Connect from a terminal" that reveals the original two command
  boxes (`commands.installOnly`, `commands.runOnly`) with the prior guide text,
  for Linux/headless executors.
- **TIP** reworded: "That computer should be a Mac that stays on — your main
  machine, a spare laptop, a mini in the closet. (Linux/servers can still connect
  via the terminal option above.)"
- **Eyebrow-meta:** "installs CLI + starts the executor" → "download app + paste
  connect". **Footer status:** "Install/connect command will be generated on
  demand" → "Download link + connect command will be generated on demand".

### 2. Bro-detail offline header

The app auto-supervises and auto-reconnects, so the primary CTA becomes opening
the app rather than running a terminal command:

- Keep "{node} is offline" / "{bro} can't take new messages until this computer
  reconnects…" and the "Auto-retrying" pip.
- Foot line: "Run on **{node}** to bring it back — it already has the CLI
  installed." → "**Open the Newbro app on {node}** — it reconnects on its own.
  Not set up there yet? Copy the connect command below and paste it into the app."
- Keep the masked `newbro executor run --token ••••••` box (copy `runOnly`).
- "Reinstall or update the CLI" disclosure → "The app keeps the CLI updated
  automatically. Advanced: reinstall from a terminal", still revealing the
  `commands.installConnect` (`curl … install.sh`) box.
- **Mobile** body line: "Copy or share Install + connect from desktop, then run
  it in Terminal on the computer that should work for this bro." → "Copy the
  connect command from desktop, then paste it into the Newbro app on that
  computer."

### 3. Home — "Add a bro" tile

- `home-add-sub`: "Generates an install/connect command" → "Download the app +
  connect a computer."

## Testing

- No command-builder logic changes, so `lib/session-client.test.ts` is
  unaffected (the generated command strings are identical).
- Update UI string/snapshot assertions that reference the changed copy
  (e.g. tests under `src/newbro/ui/src/__tests__/` or component tests that assert
  the old STEP 3 / offline / home strings) to the new strings.
- Add/keep a test asserting the **Download the Newbro app** control links to
  `APP_DOWNLOAD_URL`.
- Run the UI test suite (`npm test` in `src/newbro/ui`) to confirm green.

## Out of scope (YAGNI)

- A `newbro://` deep link or downloadable connect file for one-click handoff.
- Any change to the command-builder logic or the connect-command format.
- Per-architecture DMG auto-detection in the web UI (the GitHub releases page
  lets the user pick arm64/x86_64).
- A branded `newbro.dev/download` redirect (using the GitHub releases URL
  directly).
