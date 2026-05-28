/* variants-onboarding.jsx — first-run & offline states.
 *
 * Adds 4 artboards to the design canvas:
 *   - SignInVariant         — email + invitation code gate
 *   - FirstRunHomeVariant   — empty workspace, prompt to create a bro
 *   - CreateBroVariant      — bottom sheet to create & connect (waiting for local node)
 *   - ThreadsOfflineVariant — bro detail with connector closed; send disabled
 *
 * All four wrap in <IOSDevice 402x874> so they sit cleanly next to Home and Threads.
 * These are static design states — no shared voice context — so they can be read at a glance.
 */

// ─────────────────────────────────────────────────────────────
// SHARED
// ─────────────────────────────────────────────────────────────
function NewbroWordmark() {
  return (
    <span className="ob-wordmark">
      <span className="ob-wordmark-text">newbro</span>
      <span className="ob-wordmark-build">alpha</span>
    </span>
  );
}

// 8-char invite code field; coral caret on active cell.
function InviteCodeField({ value, focusIndex }) {
  const chars = value.split("");
  return (
    <div className="ob-invite-row" role="group" aria-label="Invitation code">
      {Array.from({ length: 8 }).map((_, i) => {
        const ch = chars[i] || "";
        const filled = !!ch;
        const cur = i === focusIndex;
        return (
          <React.Fragment key={i}>
            <span className={`ob-invite-cell${filled ? " ob-invite-cell-on" : ""}${cur ? " ob-invite-cell-cur" : ""}`}>
              <span className="ob-invite-glyph">{ch}</span>
              {cur && <span className="ob-invite-caret" aria-hidden="true" />}
            </span>
            {i === 3 && <span className="ob-invite-sep" aria-hidden="true">–</span>}
          </React.Fragment>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// 1. SIGN-IN
// ─────────────────────────────────────────────────────────────
function SignInVariant() {
  return (
    <IOSDevice width={402} height={874}>
      <div className="ob-page ob-signin">
        <header className="ob-signin-bar">
          <div className="ob-signin-logo">
            <img src="assets/newbro-logo.webp" alt="" draggable={false} />
          </div>
          <NewbroWordmark />
          <span className="ob-signin-build">0.4.2</span>
        </header>

        <main className="ob-signin-main">
          <span className="ob-eyebrow ob-eyebrow-coral">INVITATION ONLY · CLOSED ALPHA</span>
          <h1 className="ob-h1">Hi there.<br/>Let's get you in.</h1>
          <p className="ob-sub">
            Newbro is a small crew of bros — each one bound to an executor on
            a machine you trust. They keep working while you keep talking.
          </p>

          <form className="ob-form" onSubmit={(e) => e.preventDefault()}>
            <label className="ob-field">
              <span className="ob-field-eyebrow">YOUR EMAIL</span>
              <div className="ob-input ob-input-filled">
                <span className="ob-input-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="5" width="18" height="14" rx="2.5"/>
                    <path d="M3 7l9 6 9-6"/>
                  </svg>
                </span>
                <input type="email" defaultValue="luna@buildmail.dev" />
                <span className="ob-input-check" aria-hidden="true">
                  <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M4 12.5L10 18L20 6"/>
                  </svg>
                </span>
              </div>
              <span className="ob-field-hint">This becomes your workspace handle.</span>
            </label>

            <label className="ob-field">
              <span className="ob-field-eyebrow">INVITATION CODE</span>
              <InviteCodeField value="K7P4Q9R" focusIndex={7} />
              <span className="ob-field-hint">
                From the email we sent — 8 characters, case-insensitive.
              </span>
            </label>

            <button type="submit" className="ob-cta">
              <span>Continue</span>
              <kbd className="ob-cta-kbd">↵</kbd>
            </button>

            <div className="ob-foot">
              <span>Don't have an invite?</span>
              <button type="button" className="ob-link">Request access</button>
            </div>
          </form>
        </main>

        <footer className="ob-signin-footer">
          <span className="ob-mono-tiny">no accounts · no passwords · invitation tokens only</span>
        </footer>
      </div>
    </IOSDevice>
  );
}
window.SignInVariant = SignInVariant;
window.InviteCodeField = InviteCodeField;

// ─────────────────────────────────────────────────────────────
// CreateBroSheet — shared by FirstRunHomeVariant (overlay)
// and CreateBroVariant (standalone artboard).
// ─────────────────────────────────────────────────────────────
function CreateBroSheet({ onClose }) {
  return (
    <section className="ob-sheet">
      <div className="ob-sheet-handle" aria-hidden="true" />
      <header className="ob-sheet-head">
        <div className="ob-sheet-titles">
          <span className="ob-eyebrow ob-eyebrow-coral">NEW BRO</span>
          <h2 className="ob-sheet-h">Name it, then connect a node.</h2>
        </div>
        <button type="button" className="ob-sheet-close" aria-label="Close" onClick={onClose}>
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        </button>
      </header>

      <div className="ob-sheet-body">
        <div className="ob-fieldset">
          <label className="ob-field">
            <span className="ob-field-eyebrow">NAME</span>
            <div className="ob-input ob-input-filled">
              <span className="ob-input-prefix">@</span>
              <input type="text" defaultValue="atlas" />
            </div>
            <span className="ob-field-hint">One word, easy to say out loud. e.g. atlas, scout, forge, muse.</span>
          </label>
        </div>

        <div className="ob-fieldset">
          <span className="ob-field-eyebrow ob-fieldset-eyebrow">EXECUTOR</span>
          <div className="ob-exec-grid">
            <div className="ob-exec-card ob-exec-card-on">
              <span className="ob-exec-check" aria-hidden="true">
                <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 12.5L10 18L20 6"/>
                </svg>
              </span>
              <span className="ob-exec-name">Codex</span>
              <span className="ob-exec-desc">Long-running agent · shell + browser</span>
            </div>
            <div className="ob-exec-card">
              <span className="ob-exec-name">Hermes</span>
              <span className="ob-exec-desc">Headless · ops + scripts</span>
            </div>
          </div>
        </div>

        <div className="ob-fieldset">
          <div className="ob-fieldset-eyebrow-row">
            <span className="ob-field-eyebrow">CONNECT A NODE</span>
            <span className="ob-fieldset-eyebrow-meta">expires in 9:46</span>
          </div>
          <div className="ob-connect">
            <div className="ob-connect-cmd">
              <span className="ob-connect-prompt">$</span>
              <span className="ob-connect-line">
                npx newbro connect <span className="ob-connect-tok">--token K7P4Q9R-1f3a</span>
              </span>
              <button type="button" className="ob-connect-copy" aria-label="Copy command">
                <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="9" y="9" width="11" height="11" rx="2"/>
                  <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
                </svg>
              </button>
            </div>
            <div className="ob-connect-status">
              <span className="ob-connect-spinner" aria-hidden="true">
                <span /><span /><span />
              </span>
              <span className="ob-connect-status-text">
                <strong>Listening for atlas…</strong>
                <span>Run that command on the machine where atlas should work.</span>
              </span>
              <span className="ob-connect-time">0:14</span>
            </div>
          </div>
          <div className="ob-connect-meta">
            <button type="button" className="ob-link ob-link-sm">Rotate token</button>
            <span className="ob-connect-meta-sep">·</span>
            <button type="button" className="ob-link ob-link-sm">How does this work?</button>
          </div>
        </div>
      </div>

      <footer className="ob-sheet-foot">
        <button type="button" className="ob-cta ob-cta-pending" disabled>
          <span className="ob-cta-spinner" aria-hidden="true" />
          <span>Waiting for node…</span>
        </button>
      </footer>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 2. EMPTY HOME (first-run, no bros yet)
// ─────────────────────────────────────────────────────────────
function FirstRunHomeVariant() {
  const [sheetOpen, setSheetOpen] = React.useState(false);
  return (
    <IOSDevice width={402} height={874}>
      <div className={`home ob-firsthome${sheetOpen ? " ob-firsthome-sheet" : ""}`}>
        {/* same top bar as Home, but greeting is empty-state */}
        <header className="home-bar">
          <div className="home-bar-l">
            <div className="home-bar-logo">
              <img src="assets/newbro-logo.webp" alt="" draggable={false} />
            </div>
            <div className="home-bar-titles">
              <div className="home-bar-greet">Hi, Luna</div>
              <div className="home-bar-meta">workspace is empty · let's fix that</div>
            </div>
          </div>
          <button type="button" className="home-bar-btn" aria-label="Settings">
            <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3"/>
              <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9c.2.6.7 1 1.5 1H21a2 2 0 1 1 0 4h-.1c-.7 0-1.3.4-1.5 1z"/>
            </svg>
          </button>
        </header>

        <main className="ob-firsthome-body">
          {/* hero card */}
          <section className="ob-hero-card">
            <div className="ob-hero-art">
              <div className="ob-hero-art-bg" aria-hidden="true">
                {Array.from({ length: 28 }).map((_, i) => <i key={i} style={{ animationDelay: `${(i % 7) * 0.15}s` }} />)}
              </div>
              <div className="ob-hero-mascot">
                <img src="assets/newbro-logo.webp" alt="" draggable={false} />
              </div>
              <span className="ob-hero-zzz" aria-hidden="true">
                <i>z</i><i>z</i><i>z</i>
              </span>
            </div>
            <div className="ob-hero-body">
              <span className="ob-eyebrow ob-eyebrow-coral">YOUR CREW · 0 BROS</span>
              <h2 className="ob-hero-h">You don't have a bro yet.</h2>
              <p className="ob-hero-sub">
                A <strong>bro</strong> is a worker persona bound to an
                executor on one of your machines. Create one, connect a
                node, and they'll start showing up here.
              </p>
              <div className="ob-hero-actions">
                <button type="button" className="ob-cta ob-cta-block" onClick={() => setSheetOpen(true)}>
                  <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 5v14M5 12h14"/>
                  </svg>
                  <span>Create your first bro</span>
                </button>
              </div>
            </div>
          </section>

          {/* ghost rows — quietly suggest "this is where bros will go" */}
          <section className="ob-ghost-section">
            <div className="ob-explain-head">
              <span className="ob-eyebrow">STANDING BY · 0</span>
            </div>
            <div className="ob-ghost-list">
              <div className="ob-ghost-row">
                <span className="ob-ghost-avatar" />
                <span className="ob-ghost-lines">
                  <span className="ob-ghost-line ob-ghost-line-lg" />
                  <span className="ob-ghost-line ob-ghost-line-sm" />
                </span>
                <span className="ob-ghost-chip" />
              </div>
              <div className="ob-ghost-row">
                <span className="ob-ghost-avatar" />
                <span className="ob-ghost-lines">
                  <span className="ob-ghost-line ob-ghost-line-md" />
                  <span className="ob-ghost-line ob-ghost-line-sm" />
                </span>
                <span className="ob-ghost-chip" />
              </div>
            </div>
            <div className="ob-ghost-foot">
              These seats fill up after you connect a bro.
            </div>
          </section>
        </main>

        {/* the sheet — toggled by the hero CTA */}
        {sheetOpen && (
          <React.Fragment>
            <div className="ob-sheet-dim" onClick={() => setSheetOpen(false)} aria-hidden="true" />
            <CreateBroSheet onClose={() => setSheetOpen(false)} />
          </React.Fragment>
        )}
      </div>
    </IOSDevice>
  );
}
window.FirstRunHomeVariant = FirstRunHomeVariant;
window.CreateBroSheet = CreateBroSheet;

// ─────────────────────────────────────────────────────────────
// 3. CREATE + CONNECT BRO — standalone artboard view
// (the sheet itself lives in CreateBroSheet above; here we just
//  render it open over a hinted home shell.)
// ─────────────────────────────────────────────────────────────
function CreateBroVariant() {
  return (
    <IOSDevice width={402} height={874}>
      <div className="ob-page ob-create">
        <div className="ob-create-bg" aria-hidden="true">
          <div className="home-bar ob-create-bg-bar">
            <div className="home-bar-l">
              <div className="home-bar-logo">
                <img src="assets/newbro-logo.webp" alt="" draggable={false} />
              </div>
              <div className="home-bar-titles">
                <div className="home-bar-greet">Hi, Luna</div>
                <div className="home-bar-meta">setting up your first bro…</div>
              </div>
            </div>
          </div>
          <div className="ob-create-bg-strip">
            <div className="ob-create-bg-card" />
            <div className="ob-create-bg-card ob-create-bg-card-2" />
          </div>
          <div className="ob-create-bg-dim" />
        </div>

        <CreateBroSheet onClose={() => {}} />
      </div>
    </IOSDevice>
  );
}
window.CreateBroVariant = CreateBroVariant;

// ─────────────────────────────────────────────────────────────
// 4. THREADS — connector offline / closed
// ─────────────────────────────────────────────────────────────
function ThreadsOfflineVariant() {
  return (
    <IOSDevice width={402} height={874}>
      <div className="thr ob-thr-offline">
        <header className="thr-bar">
          <button type="button" className="thr-back" aria-label="Back">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 6l-6 6 6 6"/>
            </svg>
          </button>
          <div className="thr-bar-bro">
            <div className="thr-bar-avatar ob-avatar-offline">
              <img src="assets/newbro-logo.webp" alt="" draggable={false} />
              <span className="ob-avatar-offline-pip" aria-hidden="true" />
            </div>
            <div className="thr-bar-meta">
              <div className="thr-bar-title-row">
                <span className="thr-bar-name">Atlas</span>
                <span className="thr-bar-sep">·</span>
                <span className="thr-bar-thread-title">SFO → JFK options</span>
              </div>
              <div className="thr-bar-state thr-bar-state-warn">
                <span className="thr-bar-dot" />
                Offline · Studio Mac
              </div>
            </div>
          </div>
          <button type="button" className="thr-more" aria-label="More">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="6" cy="12" r="1.5" fill="currentColor"/>
              <circle cx="12" cy="12" r="1.5" fill="currentColor"/>
              <circle cx="18" cy="12" r="1.5" fill="currentColor"/>
            </svg>
          </button>
        </header>

        {/* offline banner */}
        <div className="ob-offline-banner">
          <span className="ob-offline-banner-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M2 8.5a18 18 0 0 1 20 0"/>
              <path d="M5 12.5a13 13 0 0 1 14 0"/>
              <path d="M8.5 16a8 8 0 0 1 7 0"/>
              <circle cx="12" cy="20" r="0.9" fill="currentColor"/>
              <path d="M3 3l18 18"/>
            </svg>
          </span>
          <div className="ob-offline-banner-body">
            <strong>Studio Mac is offline.</strong>
            <span>Atlas can't take new messages until the node reconnects. Your last turn is saved.</span>
          </div>
          <button type="button" className="ob-offline-banner-action">
            <span>Reconnect</span>
            <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14M13 6l6 6-6 6"/>
            </svg>
          </button>
        </div>

        {/* prior history (static snapshot) */}
        <main className="thr-thread ob-thr-thread">
          <div className="thr-day"><span>Today · 14:22</span></div>

          <div className="thr-turn thr-turn-you">
            <div className="thr-bubble thr-bubble-you">
              Compare three SFO → JFK options for Friday — red-eye okay.
            </div>
            <div className="thr-meta">Voice · 0:06 · transcribed</div>
          </div>

          <div className="thr-turn thr-turn-bro">
            <div className="thr-bubble thr-bubble-bro">
              Got it. Pulling fares from United, Delta, JetBlue. Back in a minute.
            </div>
            <div className="thr-meta">14:22</div>
          </div>

          <div className="thr-turn thr-turn-bro">
            <div className="thr-bubble thr-bubble-bro">
              Three landed. Delta non-stop wins on price and timing — JFK by 6:18a Sat. Want me to hold a seat?
            </div>
            <button type="button" className="thr-artifact">
              <span className="thr-artifact-icon">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>
                </svg>
              </span>
              <span className="thr-artifact-body">
                <span className="thr-artifact-name">sfo-jfk-fri.csv</span>
                <span className="thr-artifact-meta">csv · 3 rows · 1.2 KB</span>
              </span>
              <span className="thr-artifact-arrow">›</span>
            </button>
            <div className="thr-meta">14:23</div>
          </div>

          {/* system event marker */}
          <div className="thr-turn thr-turn-sys">
            <div className="ob-sys-event">
              <span className="ob-sys-event-dot" />
              <span><strong>Studio Mac</strong> went offline · 14:31</span>
            </div>
          </div>

          {/* the last unsent message */}
          <div className="thr-turn thr-turn-you">
            <div className="thr-bubble thr-bubble-you ob-bubble-failed">
              Yes, hold the Delta one if it's still under $480.
            </div>
            <div className="thr-meta ob-meta-failed">
              <span className="ob-meta-failed-icon" aria-hidden="true">!</span>
              <span>Not delivered · waiting for node</span>
              <button type="button" className="ob-meta-retry">Retry when online</button>
            </div>
          </div>
        </main>

        {/* disabled composer */}
        <footer className="thr-composer ob-composer-disabled">
          <div className="ob-composer-lock">
            <span className="ob-composer-lock-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="5" y="11" width="14" height="9" rx="2"/>
                <path d="M8 11V8a4 4 0 0 1 8 0v3"/>
              </svg>
            </span>
            <span className="ob-composer-lock-text">Sending paused while Studio Mac is offline.</span>
          </div>
          <div className="thr-composer-row ob-composer-row-disabled" aria-disabled="true">
            <div className="thr-ptt-idle ob-ptt-idle-disabled">
              <span className="thr-ptt-idle-dot" aria-hidden="true" />
              <span className="thr-ptt-idle-text">Hold to talk · unavailable</span>
            </div>
            <button
              type="button"
              className="thr-mic-btn thr-mic-btn-idle ob-mic-disabled"
              disabled
              aria-label="Hold to talk · node offline"
            >
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="9" y="3" width="6" height="12" rx="3"/>
                <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
                <path d="M3 3l18 18"/>
              </svg>
            </button>
          </div>
        </footer>
      </div>
    </IOSDevice>
  );
}
window.ThreadsOfflineVariant = ThreadsOfflineVariant;
