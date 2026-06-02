# Newbro Executor — Unsigned Install on Other Macs — Design

Status: design (approved for planning)
Date: 2026-06-02

## Summary

Let the unsigned `Newbro Executor.app` run on other Macs without recipients
needing `xattr`, while staying free of a paid Apple Developer account
(notarization is out of scope). The recipient does a **one-time GUI approval**
on first launch; they never touch the terminal.

This is documentation plus a one-line ad-hoc bundle seal in the build script —
no distribution pipeline, no notarization.

## Context / Facts

- The app is **ad-hoc signed** by the Swift linker (required to run on Apple
  Silicon) but **not** Developer-ID signed or notarized.
- A locally built app carries **no `com.apple.quarantine`** flag, so it runs on
  the build machine with no prompt. The flag is added only when the app is
  *downloaded/AirDropped* (quarantine-aware GUI apps), which is the case when
  shared to another Mac.
- For a quarantined, non-notarized app, Gatekeeper blocks the first launch; the
  user must explicitly approve it once. The approval UI **differs by macOS
  version** (Apple changed it in Sequoia).

## Decisions

- **Path B (document the one-time approval).** No `curl` installer, no
  notarization.
- **Seal the bundle ad-hoc** in `package-app.sh` so the whole bundle (Info.plist
  included) has a valid signature. This makes the recipient get the
  *overridable* "unverified developer" dialog rather than an "app is damaged"
  error (which cannot be cleared via "Open Anyway").

## Changes

### 1. `macos/package-app.sh` — ad-hoc seal the bundle

After the bundle is assembled (binary copied + Info.plist written), add:

```bash
codesign --force --deep --sign - "$APP"
```

`--sign -` is an ad-hoc signature (no certificate, no account). This seals the
bundle; it does **not** notarize and does **not** remove the recipient's
one-time approval — it only ensures the override path works.

### 2. `macos/README.md` — "Installing on another Mac" section

Add a section documenting:

1. **Build + share (you):** `./macos/package-app.sh`, then compress
   `macos/dist/Newbro Executor.app` and send it (AirDrop / download / etc.).
2. **Recipient unzips**, optionally drags the app to `/Applications`.
3. **First-launch approval (one-time):** double-click → if macOS blocks it:
   - **macOS 14 (Sonoma) or earlier:** Control-click the app → **Open** →
     **Open** in the dialog.
   - **macOS 15 (Sequoia) or later:** **System Settings → Privacy & Security**,
     scroll to Security, find "*Newbro Executor* was blocked…" → **Open Anyway**
     → confirm and authenticate (Touch ID / password).
4. After approving once, the app launches normally every time — no terminal, no
   `xattr`.
5. One line noting this is required only because the app isn't notarized (no paid
   Apple Developer account) and is a one-time, per-machine step.

## Non-Goals

- Notarization / Developer ID signing (needs the paid account).
- A `curl`-based install script or GitHub Release upload automation.
- Removing the one-time GUI approval (impossible without notarization).

## Testing / Verification

- `./macos/package-app.sh` still succeeds and `codesign -dv "…/Newbro
  Executor.app"` shows a valid ad-hoc signature over the bundle.
- `codesign --verify --deep --strict "…/Newbro Executor.app"` passes.
- The app still launches locally (no quarantine on the build machine).
- README renders with both macOS-version branches present.
- Full Swift suite (`swift test --package-path macos`) stays green (no code
  change, but confirm the build script edit didn't break packaging).
