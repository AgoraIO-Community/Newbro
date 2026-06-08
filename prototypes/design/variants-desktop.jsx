/* variants-desktop.jsx — desktop counterparts to the mobile onboarding flow.
 *
 *   - SignInDesktop          — email + invitation code, centered on paper wash
 *   - FirstRunHomeDesktop    — workbench shell, empty workspace, prompt to create
 *   - CreateBroDesktop       — empty home + centered modal to create & connect
 *   - BroDetailOfflineDesktop — detail page with offline node, send blocked
 *
 * Layout follows the design system's desktop workbench: a 248px sidebar +
 * fluid main column, glass top voice bar, hairline cards on paper.
 * Artboards target 1440×900.
 *
 * Class prefix is .dt-* (desktop). Reuses .ob-* atoms where shapes match
 * (eyebrows, CTAs, invite cells, executor cards, connect pane, offline banner).
 */

// ─────────────────────────────────────────────────────────────
// Sidebar — workspace nav + account block.
// ─────────────────────────────────────────────────────────────
const NAV_ICONS = {
  home: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 11l9-7 9 7v9a2 2 0 0 1-2 2h-4v-7H10v7H6a2 2 0 0 1-2-2z"/>
    </svg>
  ),
  bros: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="9" cy="9" r="3"/>
      <circle cx="17" cy="10" r="2.4"/>
      <path d="M3 19a6 6 0 0 1 12 0M14 19a5 5 0 0 1 7 0"/>
    </svg>
  ),
  nodes: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="7" rx="2"/>
      <rect x="3" y="13" width="18" height="7" rx="2"/>
      <path d="M7 7.5h.01M7 16.5h.01"/>
    </svg>
  ),
  threads: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z"/>
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9c.2.6.7 1 1.5 1H21a2 2 0 1 1 0 4h-.1c-.7 0-1.3.4-1.5 1z"/>
    </svg>
  ),
};

// ─────────────────────────────────────────────────────────────
// DesktopHeader — thin top bar replacing the sidebar.
// Holds brand + workspace handle on the left, optional voice
// status + account avatar on the right.
// ─────────────────────────────────────────────────────────────
function DesktopHeader({ statusPill = null, broSwitch = null }) {
  return (
    <header className="dt-header">
      <div className="dt-header-l">
        <div className="dt-header-brand">
          <div className="dt-header-brand-tile">
            <img src="assets/newbro-logo.webp" alt="" draggable={false} />
          </div>
          <span className="dt-header-brand-name">newbro</span>
        </div>
        {broSwitch && (
          <React.Fragment>
            <span className="dt-header-sep" />
            {broSwitch}
          </React.Fragment>
        )}
      </div>

      <div className="dt-header-r">
        {statusPill}
        <button type="button" className="dt-header-icon-btn" aria-label="Search">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7"/>
            <path d="M21 21l-4.3-4.3"/>
          </svg>
        </button>
        <button type="button" className="dt-header-icon-btn" aria-label="Preferences">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9c.2.6.7 1 1.5 1H21a2 2 0 1 1 0 4h-.1c-.7 0-1.3.4-1.5 1z"/>
          </svg>
        </button>
        <button type="button" className="dt-header-account" aria-label="Account">
          <span className="dt-header-account-avatar">L</span>
          <span className="dt-header-account-name">Luna</span>
          <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M6 9l6 6 6-6"/>
          </svg>
        </button>
      </div>
    </header>
  );
}

// Compact status pill used in the header — mirrors the top voice bar but inline.
function HeaderStatusPill({ status, label }) {
  return (
    <span className={`dt-header-pill dt-header-pill-${status}`}>
      <span className="dt-header-pill-dot" />
      {label}
    </span>
  );
}

// Map bro name → character glyph kind.
const BRO_CHAR = {
  Atlas:  "fox",
  Forge:  "rabbit",
  Scout:  "cat",
  Muse:   "person",
  Codex:  "person",
};
function broChar(name) { return BRO_CHAR[name] || "person"; }

function DesktopSidebar({ active = "home", bros = [], activeBroId = null, nodeCount = 0, broState = null, hideBros = false }) {
  const working = bros.filter((b) => b.state === "working");
  const others  = bros.filter((b) => b.state !== "working");
  return (
    <aside className="dt-sidebar">
      <div className="dt-sidebar-logo">
        <div className="dt-sidebar-logo-tile">
          <img src="assets/newbro-logo.webp" alt="" draggable={false} />
        </div>
        <div className="dt-sidebar-logo-titles">
          <span className="dt-sidebar-name">NEWBRO</span>
          <span className="dt-sidebar-sub">workspace · luna</span>
        </div>
      </div>

      <div className="dt-sidebar-scroll">
        {!hideBros && (
        <div className="dt-sidebar-section">
          <div className="dt-sidebar-crew-head">
            <span className="dt-sidebar-label">Your crew · {bros.length}</span>
            <button type="button" className="dt-sidebar-add" aria-label="Create a bro">
              <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 5v14M5 12h14"/>
              </svg>
            </button>
          </div>

          {bros.length === 0 ? (
            <div className="dt-sidebar-emptycrew">
              <span className="dt-sidebar-emptycrew-text">No bros yet.</span>
              <button type="button" className="dt-sidebar-emptycrew-cta">
                Create your first bro
              </button>
            </div>
          ) : (
            <div className="dt-sidebar-bros">
              {working.length > 0 && (
                <div className="dt-sidebar-broset">
                  <span className="dt-sidebar-broset-label">In flight</span>
                  {working.map((b) => (
                    <DTSidebarBroRow key={b.id} bro={b} on={b.id === activeBroId} />
                  ))}
                </div>
              )}
              {others.length > 0 && (
                <div className="dt-sidebar-broset">
                  <span className="dt-sidebar-broset-label">Standing by</span>
                  {others.map((b) => (
                    <DTSidebarBroRow key={b.id} bro={b} on={b.id === activeBroId} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
        )}

        {/* legacy single-bro highlight (used by empty-state pages that pass broState) */}
        {broState && (
          <div className="dt-sidebar-section">
            <span className="dt-sidebar-label">Your crew</span>
            <div className="dt-sidebar-bro">
              <div className={`dt-sidebar-bro-avatar dt-sidebar-bro-avatar-${broState.tone}`}>
                <img src="assets/newbro-logo.webp" alt="" draggable={false} />
                <span className="dt-sidebar-bro-pip" />
              </div>
              <div className="dt-sidebar-bro-meta">
                <span className="dt-sidebar-bro-name">{broState.name}</span>
                <span className={`dt-sidebar-bro-state dt-sidebar-bro-state-${broState.tone}`}>
                  {broState.label}
                </span>
              </div>
            </div>
          </div>
        )}

        <div className="dt-sidebar-section">
          <span className="dt-sidebar-label">Settings</span>
          <button type="button" className="dt-nav-btn">
            <span className="dt-nav-icon">{NAV_ICONS.settings}</span>
            <span>Preferences</span>
          </button>
        </div>
      </div>

      <div className="dt-sidebar-account">
        <div className="dt-sidebar-account-avatar">L</div>
        <div className="dt-sidebar-account-meta">
          <span className="dt-sidebar-account-name">Luna</span>
          <span className="dt-sidebar-account-id">luna@buildmail.dev</span>
        </div>
        <button type="button" className="dt-sidebar-account-out" aria-label="Sign out">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
            <path d="M16 17l5-5-5-5M21 12H9M12 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7"/>
          </svg>
        </button>
      </div>
    </aside>
  );
}

// Compact bro row used inside the sidebar.
function DTSidebarBroRow({ bro, on }) {
  const tone =
    bro.state === "working" ? "info" :
    bro.state === "offline" ? "warn" :
    "calm";
  const stateLine =
    bro.state === "working" ? `working · ${bro.progress}%` :
    bro.state === "offline" ? "offline · " + (bro.node || "") :
    "standing by";
  return (
    <button type="button" className={`dt-sidebar-bro-row${on ? " dt-sidebar-bro-row-on" : ""}`}>
      <div className={`dt-sidebar-bro-row-avatar dt-sidebar-bro-row-avatar-${tone}`}>
        <BroAvatar character={broChar(bro.name)} state={bro.state} size={26} />
        <span className={`dt-sidebar-bro-row-pip dt-sidebar-bro-row-pip-${tone}`} />
      </div>
      <div className="dt-sidebar-bro-row-meta">
        <span className="dt-sidebar-bro-row-name">{bro.name}</span>
        <span className={`dt-sidebar-bro-row-state dt-sidebar-bro-row-state-${tone}`}>
          {stateLine}
        </span>
      </div>
      {bro.unread > 0 && (
        <span className="dt-sidebar-bro-row-badge">{bro.unread}</span>
      )}
    </button>
  );
}

// Glass top bar — status pills + voice control row.
function DesktopTopVoiceBar({ status = "ready", note = "No bros connected yet.", showControls = false }) {
  return (
    <div className="dt-topvoice">
      <div className="dt-topvoice-pills">
        <span className={`dt-topvoice-pill dt-topvoice-pill-${status}`}>
          <span className="dt-topvoice-pill-dot" />
          {status === "ready"   && "READY"}
          {status === "live"    && "LIVE · listening"}
          {status === "paused"  && "PAUSED · computer offline"}
          {status === "empty"   && "STANDBY"}
        </span>
        <span className="dt-topvoice-note">{note}</span>
      </div>
      {showControls && (
        <div className="dt-topvoice-actions">
          <button type="button" className="dt-topvoice-btn">
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="3" width="6" height="12" rx="3"/>
              <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
            </svg>
            <span>Mute</span>
          </button>
          <button type="button" className="dt-topvoice-btn dt-topvoice-btn-primary">
            <span>Start session</span>
          </button>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// 1. SIGN-IN  — centered card on paper wash
// ─────────────────────────────────────────────────────────────
function SignInDesktop() {
  return (
    <div className="dt-frame dt-signin">
      {/* paper grid backdrop */}
      <div className="dt-signin-bg" aria-hidden="true" />

      {/* tiny top brand mark */}
      <div className="dt-signin-brand">
        <div className="dt-signin-brand-tile">
          <img src="assets/newbro-logo.webp" alt="" draggable={false} />
        </div>
        <span className="ob-wordmark">
          <span className="ob-wordmark-text">newbro</span>
          <span className="ob-wordmark-build">alpha</span>
        </span>
        <span className="dt-signin-build">build 0.4.2 · closed alpha</span>
      </div>

      {/* the card */}
      <div className="dt-signin-card">
        <div className="dt-signin-card-l">
          <span className="ob-eyebrow ob-eyebrow-coral">INVITATION ONLY</span>
          <h1 className="dt-h1">Hi there.<br/>Let's get you in.</h1>
          <p className="dt-sub">
            Newbro is a small crew of bros — each one lives on a computer you
            trust and keeps working while you talk. No setup headaches.
          </p>
          <ul className="dt-signin-bullets">
            <li>
              <span className="dt-signin-bullet-dot" />
              <span>One workspace per email.</span>
            </li>
            <li>
              <span className="dt-signin-bullet-dot" />
              <span>Connect your own computers — a Mac, a spare laptop, anything that stays on.</span>
            </li>
            <li>
              <span className="dt-signin-bullet-dot" />
              <span>Voice-first — no passwords, just invitation tokens.</span>
            </li>
          </ul>
        </div>

        <form className="dt-signin-card-r" onSubmit={(e) => e.preventDefault()}>
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
            <span className="ob-field-hint">From the email we sent — 8 characters, case-insensitive.</span>
          </label>

          <button type="submit" className="ob-cta dt-signin-cta">
            <span>Continue</span>
            <kbd className="ob-cta-kbd">↵</kbd>
          </button>

          <div className="ob-foot">
            <span>Don't have an invite?</span>
            <button type="button" className="ob-link">Request access</button>
          </div>
        </form>
      </div>

      <div className="dt-signin-footer">
        <span className="ob-mono-tiny">no accounts · no passwords · invitation tokens only</span>
      </div>
    </div>
  );
}
window.SignInDesktop = SignInDesktop;

// ─────────────────────────────────────────────────────────────
// 2. EMPTY HOME — workbench shell, prompt to create
// ─────────────────────────────────────────────────────────────
function FirstRunHomeDesktop() {
  const [sheetOpen, setSheetOpen] = React.useState(false);
  return (
    <div className={`dt-frame dt-shell${sheetOpen ? " dt-shell-modal" : ""}`}>
      <DesktopHeader statusPill={<HeaderStatusPill status="empty" label="STANDBY" />} />
      <main className="dt-main">
        <div className="dt-empty-stage">
          <div className="dt-empty-art-lg" aria-hidden="true">
            <div className="dt-empty-grid-lg">
              {Array.from({ length: 80 }).map((_, i) => <i key={i} style={{ animationDelay: `${(i % 9) * 0.12}s` }} />)}
            </div>
            <div className="dt-empty-mascot-lg">
              <img src="assets/newbro-logo.webp" alt="" draggable={false} />
            </div>
            <span className="dt-empty-zzz-lg" aria-hidden="true">
              <i>z</i><i>z</i><i>z</i>
            </span>
          </div>

          <div className="dt-empty-copy">
            <span className="ob-eyebrow ob-eyebrow-coral">YOUR CREW · 0 BROS</span>
            <h1 className="dt-empty-h-lg">You don't have a bro yet.</h1>
            <p className="dt-empty-sub-lg">
              A <strong>bro</strong> is a teammate that works on a computer
              you trust. Give it a name, connect a computer, and it'll start
              working alongside you.
            </p>
            <div className="dt-empty-actions-lg">
              <button type="button" className="ob-cta dt-empty-cta-lg" onClick={() => setSheetOpen(true)}>
                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 5v14M5 12h14"/>
                </svg>
                <span>Create your first bro</span>
              </button>
            </div>
          </div>
        </div>
      </main>

      {sheetOpen && (
        <React.Fragment>
          <div className="dt-modal-dim" onClick={() => setSheetOpen(false)} aria-hidden="true" />
          <CreateBroModal onClose={() => setSheetOpen(false)} />
        </React.Fragment>
      )}
    </div>
  );
}
window.FirstRunHomeDesktop = FirstRunHomeDesktop;

// ─────────────────────────────────────────────────────────────
// CreateBroModal — centered dialog used by FirstRunHomeDesktop
// and CreateBroDesktop.
// ─────────────────────────────────────────────────────────────
function CreateBroModal({ onClose }) {
  return (
    <div className="dt-modal" role="dialog" aria-label="Create a new bro">
      <header className="dt-modal-head">
        <div className="dt-modal-titles">
          <span className="ob-eyebrow ob-eyebrow-coral">NEW BRO</span>
          <h2 className="dt-modal-h">Set up your first bro</h2>
          <p className="ob-sheet-intro">A bro works on a computer you keep on — your Mac, a spare laptop, anything. Three quick steps and it's ready.</p>
        </div>
        <button type="button" className="dt-modal-close" aria-label="Close" onClick={onClose}>
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        </button>
      </header>

      <div className="dt-modal-body">
        <div className="dt-modal-cols">
          {/* LEFT — name + executor */}
          <div className="dt-modal-col">
            <div className="ob-fieldset">
              <label className="ob-field">
                <span className="ob-field-eyebrow">STEP 1 · NAME IT</span>
                <div className="ob-input ob-input-filled">
                  <span className="ob-input-prefix">@</span>
                  <input type="text" defaultValue="atlas" />
                </div>
                <span className="ob-field-hint">Pick one word that's easy to say out loud — you'll talk to it by name. e.g. atlas, scout, forge.</span>
              </label>
            </div>

            <div className="ob-fieldset">
              <span className="ob-field-eyebrow ob-fieldset-eyebrow">STEP 2 · AGENT CLIENT</span>
              <div className="ob-exec-grid">
                <div className="ob-exec-card ob-exec-card-on">
                  <span className="ob-exec-name">Codex</span>
                  <span className="ob-exec-desc">OpenAI&rsquo;s coding agent</span>
                  <span className="ob-exec-check" aria-hidden="true">
                    <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M4 12.5L10 18L20 6"/>
                    </svg>
                  </span>
                </div>
                <div className="ob-exec-card">
                  <span className="ob-exec-name">Hermes</span>
                  <span className="ob-exec-desc">Open-source agent by Nous Research</span>
                </div>
              </div>
              <span className="ob-field-hint">Pick the one you already use — newbro runs your tasks through it. You can switch anytime.</span>
            </div>
          </div>

          {/* RIGHT — connector */}
          <div className="dt-modal-col">
            <div className="ob-fieldset">
              <div className="ob-fieldset-eyebrow-row">
                <span className="ob-field-eyebrow">STEP 3 · CONNECT A COMPUTER</span>
                <span className="ob-fieldset-eyebrow-meta">expires in 9:46</span>
              </div>
              <p className="ob-connect-guide">On the computer where atlas should work, paste this in a terminal to install newbro:</p>
              <div className="ob-connect">
                <div className="ob-connect-cmd">
                  <span className="ob-connect-prompt">$</span>
                  <span className="ob-connect-line">
                    curl -fsSL <span className="ob-connect-tok">newbro.dev/install.sh</span> | sh
                  </span>
                  <button type="button" className="ob-connect-copy" aria-label="Copy install command">
                    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="9" y="9" width="11" height="11" rx="2"/>
                      <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
                    </svg>
                  </button>
                </div>
              </div>
              <p className="ob-connect-guide ob-connect-guide-2">Then start it with your one-time key — we filled in the details for you:</p>
              <div className="ob-connect">
                <div className="ob-connect-cmd ob-connect-cmd-multi">
                  <span className="ob-connect-prompt">$</span>
                  <span className="ob-connect-line">
                    newbro executor run <span className="ob-connect-tok">--token MRElL_T251_gUOuC</span>
                  </span>
                  <button type="button" className="ob-connect-copy" aria-label="Copy connect command">
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
                    <strong>Waiting to hear from your computer…</strong>
                    <span>This updates on its own once atlas connects. Nothing else on that computer changes.</span>
                  </span>
                  <span className="ob-connect-time">0:14</span>
                </div>
              </div>
              <div className="ob-connect-meta">
                <button type="button" className="ob-link ob-link-sm">Get a fresh link</button>
                <span className="ob-connect-meta-sep">·</span>
                <button type="button" className="ob-link ob-link-sm">Walk me through it</button>
              </div>
            </div>

            <div className="dt-modal-tip">
              <span className="dt-modal-tip-eyebrow">TIP</span>
              <p>
                That computer can be anything that stays on — your Mac, a spare
                laptop, a mini in the closet. atlas only runs there when you ask
                it to, and you can move it to another computer anytime.
              </p>
            </div>
          </div>
        </div>
      </div>

      <footer className="dt-modal-foot">
        <span className="dt-modal-foot-status">
          <span className="dt-modal-foot-dot" />
          We'll detect your computer automatically · link valid 9:46
        </span>
        <button type="button" className="ob-cta ob-cta-pending dt-modal-cta" disabled>
          <span className="ob-cta-spinner" aria-hidden="true" />
          <span>Waiting for your computer…</span>
        </button>
      </footer>
    </div>
  );
}
window.CreateBroModal = CreateBroModal;

// ─────────────────────────────────────────────────────────────
// 3. CREATE + CONNECT (standalone artboard)
// ─────────────────────────────────────────────────────────────
function CreateBroDesktop() {
  return (
    <div className="dt-frame dt-shell dt-shell-modal">
      <DesktopHeader statusPill={<HeaderStatusPill status="empty" label="STANDBY" />} />
      <main className="dt-main">
        <div className="dt-main-pad">
          <header className="dt-page-head">
            <div>
              <h1 className="dt-page-title">Home</h1>
            </div>
          </header>
          <div className="dt-empty-card dt-empty-card-hint">
            <div className="dt-empty-art" />
            <div className="dt-empty-body">
              <span className="ob-eyebrow ob-eyebrow-coral">YOUR CREW · 0 BROS</span>
              <h2 className="dt-empty-h">You don't have a bro yet.</h2>
            </div>
          </div>
        </div>
      </main>
      <div className="dt-modal-dim" aria-hidden="true" />
      <CreateBroModal onClose={() => {}} />
    </div>
  );
}
window.CreateBroDesktop = CreateBroDesktop;

// ─────────────────────────────────────────────────────────────
// Skills — packaged capabilities the bro can run this turn with.
// Picked from the composer (chip, or type "/" to filter). A chosen
// skill rides along with the next message and shapes how the bro works.
// ─────────────────────────────────────────────────────────────
const SKILL_DEFAULT_ICON = (
  <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3l1.9 4.7L19 9l-4.1 2.3L13 16l-1-4.5L7 9l4.1-1.3z"/>
    <path d="M19 15l.7 1.8L21.5 18l-1.8.7L19 21l-.7-2.3L16.5 18l1.8-1.2z"/>
  </svg>
);
const SKILLS = [
  {
    id: "deep-research",
    name: "Deep research",
    desc: "Multi-source dig with cited findings",
    hint: "what should I get to the bottom of?",
    icon: (
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/><path d="M11 8v6M8 11h6"/>
      </svg>
    ),
  },
  {
    id: "flight-search",
    name: "Flight search",
    desc: "Compare fares across airlines",
    hint: "route + dates, e.g. SFO → JFK Fri",
    icon: (
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V18l-2 1.5V21l3.5-1 3.5 1v-1.5L13 18v-4.5z"/>
      </svg>
    ),
  },
  {
    id: "stays",
    name: "Find stays",
    desc: "Rank hotels near a point",
    hint: "where, and what matters most?",
    icon: (
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 21V8l9-5 9 5v13"/><path d="M3 21h18M9 21v-6h6v6"/>
      </svg>
    ),
  },
  {
    id: "itinerary",
    name: "Build itinerary",
    desc: "Day-by-day plan you can edit",
    hint: "trip length + the vibe you want",
    icon: (
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 2v4M16 2v4M8 14h.01M12 14h.01M16 14h.01"/>
      </svg>
    ),
  },
  {
    id: "price-watch",
    name: "Price watch",
    desc: "Track and ping on drops",
    hint: "what to watch, and your ceiling",
    icon: (
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 17l5-5 4 4 8-9"/><path d="M16 7h4v4"/>
      </svg>
    ),
  },
  {
    id: "summarize",
    name: "Summarize",
    desc: "Condense a thread or document",
    hint: "paste or point me at the source",
    icon: (
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 6h16M4 11h16M4 16h10"/>
      </svg>
    ),
  },
];

// Popover that floats above the composer's lead cluster. Opens on the
// skill chip, or while typing "/" in the bar (query filters the list).
function DTSkillMenu({ query = "", selected, broName = "Atlas", onChoose, onClose }) {
  const q = query.trim().toLowerCase();
  const list = q
    ? SKILLS.filter((s) => (s.name + " " + s.desc).toLowerCase().includes(q))
    : SKILLS;
  return (
    <div className="dt-skill-pop" role="menu" aria-label="Run with a skill">
      <div className="dt-skill-pop-head">
        <span className="dt-skill-pop-title">Run with a skill</span>
        <span className="dt-skill-pop-hint">
          {query ? <React.Fragment>filtering <span className="dt-skill-pop-q">/{query}</span></React.Fragment>
                 : <React.Fragment>type <kbd className="dt-kbd">/</kbd> to filter</React.Fragment>}
        </span>
      </div>
      {list.length === 0 ? (
        <div className="dt-skill-empty">No skill matches “{query}”. Just send and {broName} figures it out.</div>
      ) : (
        <ul className="dt-skill-pop-list">
          {list.map((s) => {
            const on = selected && selected.id === s.id;
            return (
              <li key={s.id}>
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={!!on}
                  className={`dt-skill-opt${on ? " dt-skill-opt-on" : ""}`}
                  onClick={() => onChoose(s)}
                >
                  <span className="dt-skill-opt-ic" aria-hidden="true">{s.icon}</span>
                  <span className="dt-skill-opt-body">
                    <span className="dt-skill-opt-name">{s.name}</span>
                    <span className="dt-skill-opt-desc">{s.desc}</span>
                  </span>
                  {on && (
                    <svg className="dt-skill-opt-check" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M4 12.5L10 18L20 6"/>
                    </svg>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <div className="dt-skill-pop-foot">
        <span>Skills shape how {broName} works the turn</span>
        <kbd className="dt-kbd">esc</kbd>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// DTComposerBar — horizontal full-width composer.
// Mode chips (Push / Free / Type) sit as a small pill on the left
// of the head row; a hint on the right. The bar itself holds the
// text field, an optional mic button (PTT/Free), and a coral send.
// A leading cluster carries the Skill picker + Plan-mode chip.
// ─────────────────────────────────────────────────────────────
function DTComposerBar({ mode = "ptt", onMode, disabled = false, broName = "Atlas", planMode = false, onTogglePlan, onSendPlan }) {
  // Two modes:
  //   "ptt"  — push-to-talk, merged with text. Type or hold space.
  //   "free" — open channel, voice only. No typing.
  const voiceMode = mode === "free" ? "free" : "ptt";
  const opts = [
    {
      v: "ptt",
      label: "Push to talk",
      icon: (
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="3" width="6" height="11" rx="3"/>
          <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
        </svg>
      ),
    },
    {
      v: "free",
      label: "Hands-free",
      icon: (
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="10" y="4" width="4" height="9" rx="2"/>
          <path d="M6.5 8.5a6 6 0 0 0 0 7M17.5 8.5a6 6 0 0 1 0 7"/>
          <path d="M12 17v3"/>
        </svg>
      ),
    },
  ];

  // Free-mode sub-mode comes from the shared voice context so it stays in
  // sync with the tweak panel + mobile variants.
  const v = (typeof useVoice === "function") ? useVoice() : null;
  const [localSub, setLocalSub] = React.useState("silent");
  const subMode    = v ? v.freeSubMode    : localSub;
  const setSubMode = v ? v.setFreeSubMode : setLocalSub;

  // Local composer text so Enter / send / Shift+Tab can be wired.
  const [text, setText] = React.useState("");
  const inputRef = React.useRef(null);

  // Skill picker — choose a packaged capability to run this turn with.
  // Opens from the chip, or inline the instant you type "/" in the bar.
  const [skill, setSkill] = React.useState(null);
  const [skillOpen, setSkillOpen] = React.useState(false);
  const [skillQuery, setSkillQuery] = React.useState("");
  const leadRef = React.useRef(null);
  const filterSkills = (qq) => {
    const q = qq.trim().toLowerCase();
    return q ? SKILLS.filter((s) => (s.name + " " + s.desc).toLowerCase().includes(q)) : SKILLS;
  };
  const chooseSkill = (s) => {
    setSkill(s);
    setSkillOpen(false);
    setSkillQuery("");
    if (text.startsWith("/")) setText("");
    requestAnimationFrame(() => { try { inputRef.current && inputRef.current.focus(); } catch (e) {} });
  };
  const clearSkill = () => { setSkill(null); };

  // Inline "/" trigger: a leading slash opens the menu and filters by
  // whatever follows it. Deleting back past the slash closes it again.
  const onInputChange = (e) => {
    const val = e.target.value;
    setText(val);
    if (val.startsWith("/")) { setSkillOpen(true); setSkillQuery(val.slice(1)); }
    else if (skillOpen) { setSkillOpen(false); setSkillQuery(""); }
  };

  // Close the menu on outside click / Escape.
  React.useEffect(() => {
    if (!skillOpen) return;
    const onDown = (e) => { if (leadRef.current && !leadRef.current.contains(e.target)) setSkillOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [skillOpen]);

  const submit = () => {
    const t = text.trim();
    if (!t) return;
    if (planMode && onSendPlan) { onSendPlan(t); setText(""); return; }
    setText("");
  };
  const handleKey = (e) => {
    // Shift+Tab toggles plan mode (desktop shortcut)
    if (e.key === "Tab" && e.shiftKey) { e.preventDefault(); onTogglePlan && onTogglePlan(); return; }
    // While the skill menu is open, Enter picks the top match, Esc dismisses.
    if (skillOpen) {
      if (e.key === "Enter") { e.preventDefault(); const m = filterSkills(skillQuery); if (m[0]) chooseSkill(m[0]); return; }
      if (e.key === "Escape") { e.preventDefault(); setSkillOpen(false); if (text.startsWith("/")) setText(""); return; }
    }
    if (e.key === "Enter" && text.trim()) { e.preventDefault(); submit(); }
  };

  // Push-to-talk recording — press & hold the trailing mic to record,
  // release to send. Drives the in-bar live waveform + timer.
  const [recording, setRecording] = React.useState(false);
  const [recSecs, setRecSecs] = React.useState(0);
  const recTimer = React.useRef(null);
  const startRec = (e) => {
    if (disabled) return;
    if (e && e.preventDefault) e.preventDefault();
    setRecording(true);
    setRecSecs(0);
    clearInterval(recTimer.current);
    recTimer.current = setInterval(() => setRecSecs((s) => s + 1), 1000);
  };
  const stopRec = () => {
    if (!recording) return;
    clearInterval(recTimer.current);
    setRecording(false);
    setRecSecs(0);
    // (captured audio would be sent to the bro here)
  };
  React.useEffect(() => () => clearInterval(recTimer.current), []);
  const recFmt = `0:${String(recSecs).padStart(2, "0")}`;
  const hasText = text.trim().length > 0;

  // Plan-mode toggle. Lives inside the composer bar (leading the input),
  // so it reads as "what happens when I send this" rather than a third
  // talk mode sitting next to Push-to-talk / Hands-free.
  const planChip = !disabled && (
    <button
      type="button"
      className={`dt-cmp-planchip${planMode ? " dt-cmp-planchip-on" : ""}`}
      onClick={() => onTogglePlan && onTogglePlan()}
      aria-pressed={planMode}
      title={`Plan mode · Shift+Tab — ${broName} proposes a plan before acting`}
    >
      <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="9" width="6" height="6" rx="1.5"/>
        <rect x="15" y="4" width="6" height="6" rx="1.5"/>
        <rect x="15" y="14" width="6" height="6" rx="1.5"/>
        <path d="M9 12h3M12 7v10M12 7h3M12 17h3"/>
      </svg>
      <span className="dt-cmp-planchip-label">Plan{planMode ? " on" : ""}</span>
      <kbd className="dt-kbd dt-cmp-planchip-kbd">⇧⇥</kbd>
    </button>
  );

  // Leading cluster — Skill picker + Plan-mode chip, with the skill
  // popover anchored above it. Hidden entirely when the node's offline.
  const leadCluster = !disabled && (
    <div className="dt-cmp-lead" ref={leadRef}>
      {skill ? (
        <span className={`dt-cmp-skillpill${skillOpen ? " dt-cmp-skillpill-open" : ""}`}>
          <button
            type="button"
            className="dt-cmp-skillpill-body"
            onClick={() => setSkillOpen((o) => !o)}
            aria-haspopup="menu"
            aria-expanded={skillOpen}
            title={`Skill: ${skill.name} — click to change`}
          >
            <span className="dt-cmp-skillpill-ic" aria-hidden="true">{skill.icon}</span>
            <span className="dt-cmp-skillpill-name">{skill.name}</span>
          </button>
          <button
            type="button"
            className="dt-cmp-skillpill-x"
            onClick={clearSkill}
            aria-label={`Remove ${skill.name} skill`}
            title="Remove skill"
          >
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
          </button>
        </span>
      ) : (
        <button
          type="button"
          className={`dt-cmp-skillchip${skillOpen ? " dt-cmp-skillchip-open" : ""}`}
          onClick={() => setSkillOpen((o) => !o)}
          aria-haspopup="menu"
          aria-expanded={skillOpen}
          title="Run this turn with a skill"
        >
          <span className="dt-cmp-skillchip-ic" aria-hidden="true">{SKILL_DEFAULT_ICON}</span>
          <span className="dt-cmp-skillchip-label">Skill</span>
          <kbd className="dt-kbd dt-cmp-skillchip-kbd">/</kbd>
        </button>
      )}
      {planChip}
      {skillOpen && (
        <DTSkillMenu
          query={skillQuery}
          selected={skill}
          broName={broName}
          onChoose={chooseSkill}
          onClose={() => setSkillOpen(false)}
        />
      )}
    </div>
  );

  return (
    <div className={`dt-cmp dt-cmp-${voiceMode}${disabled ? " dt-cmp-disabled" : ""}${planMode ? " dt-cmp-plan" : ""}${skill ? " dt-cmp-skill" : ""}`}>
      <div className="dt-cmp-head">
        <div className="dt-cmp-headl">
          <div className="dt-cmp-modewrap">
            <span className="dt-cmp-modewrap-label">Talk mode</span>
            <div className={`dt-cmp-modes${disabled ? " dt-cmp-modes-off" : ""}`} role="tablist" aria-label="How you talk to the bro">
            {opts.map((o) => {
              const on = voiceMode === o.v;
              return (
                <button
                  key={o.v}
                  type="button"
                  role="tab"
                  aria-selected={on}
                  disabled={disabled}
                  className={`dt-cmp-mode${on ? ` dt-cmp-mode-on dt-cmp-mode-on-${o.v}` : ""}`}
                  onClick={() => !disabled && onMode && onMode(o.v)}
                >
                  <span className="dt-cmp-mode-ic" aria-hidden="true">{o.icon}</span>
                  <span>{o.label}</span>
                </button>
              );
            })}
            </div>
          </div>
        </div>

        {voiceMode === "free" && !disabled && (
          <div className={`dt-cmp-sub dt-cmp-sub-${subMode}`} role="tablist" aria-label="Always-on style">
            <span className="dt-cmp-sub-eyebrow">{broName} style</span>
            <button
              type="button"
              role="tab"
              aria-selected={subMode === "silent"}
              className={`dt-cmp-sub-opt${subMode === "silent" ? " dt-cmp-sub-opt-on" : ""}`}
              onClick={() => setSubMode("silent")}
            >
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M11 5L6 9H3v6h3l5 4z"/>
                <path d="M16 9l5 6M21 9l-5 6"/>
              </svg>
              <span>Talk less</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={subMode === "active"}
              className={`dt-cmp-sub-opt${subMode === "active" ? " dt-cmp-sub-opt-on" : ""}`}
              onClick={() => setSubMode("active")}
            >
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z"/>
              </svg>
              <span>Engage</span>
            </button>
          </div>
        )}

        <span className="dt-cmp-hint">
          {disabled
            ? <span>Sending paused — reconnect your computer to resume</span>
            : voiceMode === "ptt"
              ? (recording
                  ? <span>Recording… release the mic to send</span>
                  : hasText
                    ? <span>Press <kbd className="dt-kbd">Enter</kbd> to send</span>
                    : <span>Hold <kbd className="dt-kbd">Space</kbd> to talk, or type your message</span>)
              : subMode === "silent"
                ? <span>Mic's open — just speak; {broName} replies when you pause</span>
                : <span>Mic's open — {broName} may chime in as you go</span>}
        </span>
      </div>

      {voiceMode === "ptt" ? (
        // PTT mode — merged text + voice. Type or hold to talk.
        <div className={`dt-cmp-bar${recording ? " dt-cmp-bar-rec" : ""}${skill ? " dt-cmp-bar-skill" : ""}`}>
          {leadCluster}
          {recording ? (
            <div className="dt-cmp-rec">
              <span className="dt-cmp-rec-dot" aria-hidden="true" />
              <span className="dt-cmp-rec-label">Listening…</span>
              <span className="dt-cmp-rec-wave" aria-hidden="true">
                {Array.from({ length: 30 }).map((_, i) => {
                  const h = 5 + Math.abs(Math.sin((i + 1) * 0.6)) * 15;
                  return <i key={i} style={{ height: h, animationDelay: `${(i % 7) * 0.07}s` }} />;
                })}
              </span>
              <span className="dt-cmp-rec-time">{recFmt}</span>
              <span className="dt-cmp-rec-hint">release to send</span>
            </div>
          ) : (
            <input
              type="text"
              className="dt-cmp-input"
              disabled={disabled}
              value={text}
              ref={inputRef}
              onChange={onInputChange}
              onKeyDown={handleKey}
              placeholder={
                disabled
                  ? `${broName} can't take new messages — reconnect your computer to resume`
                  : skill
                    ? `${skill.name} — ${skill.hint}`
                    : planMode
                      ? `Describe the task — ${broName} will plan it first…`
                      : `Hold to talk, type “/” for a skill, or a message to ${broName}…`
              }
            />
          )}

          {hasText && !recording ? (
            <button
              type="button"
              className="dt-cmp-action dt-cmp-action-send"
              disabled={disabled}
              aria-label="Send message"
              onClick={submit}
            >
              <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 19V5M5 12l7-7 7 7"/>
              </svg>
            </button>
          ) : (
            <button
              type="button"
              className={`dt-cmp-action dt-cmp-action-mic dt-cmp-action-mic-${disabled ? "off" : "on"}${recording ? " dt-cmp-action-rec" : ""}`}
              disabled={disabled}
              aria-label={recording ? "Release to send" : "Hold to talk"}
              title={recording ? "Release to send" : "Press and hold to talk"}
              onPointerDown={startRec}
              onPointerUp={stopRec}
              onPointerLeave={stopRec}
              onPointerCancel={stopRec}
            >
              {recording ? (
                <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
                  <rect x="6" y="6" width="12" height="12" rx="3"/>
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="9" y="3" width="6" height="12" rx="3"/>
                  <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
                  {disabled && <path d="M3 3l18 18"/>}
                </svg>
              )}
            </button>
          )}
        </div>
      ) : (
        // Free mode — voice only, no text input. Channel-open indicator + mic.
        <div className={`dt-cmp-channel dt-cmp-channel-${subMode}${disabled ? " dt-cmp-channel-off" : ""}`}>
          {leadCluster}
          <span className={`dt-cmp-channel-led dt-cmp-channel-led-${subMode}`} aria-hidden="true" />
          <span className="dt-cmp-channel-text">
            <span className="dt-cmp-channel-title">
              {disabled ? "Mic paused" : `Hands-free · ${subMode === "silent" ? "Talk less" : "Engage"}`}
            </span>
            <span className="dt-cmp-channel-sub">
              {disabled
                ? "Reconnect your computer to resume the mic."
                : subMode === "silent"
                  ? `${broName} is listening — just speak when you're ready.`
                  : `${broName} is listening and will chime in if it helps.`}
            </span>
          </span>
          <span className="dt-cmp-channel-waves" aria-hidden="true">
            {Array.from({ length: 28 }).map((_, i) => {
              const h = 4 + Math.abs(Math.sin((i + 1) * 0.55)) * 13;
              return <i key={i} style={{ height: h, animationDelay: `${(i % 7) * 0.09}s` }} />;
            })}
          </span>
          <button
            type="button"
            className={`dt-cmp-mic dt-cmp-mic-${disabled ? "off" : "free"}`}
            disabled={disabled}
            aria-label={disabled ? "Mic paused" : "Close always-on mic"}
          >
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="3" width="6" height="12" rx="3"/>
              <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
              {disabled && <path d="M3 3l18 18"/>}
            </svg>
          </button>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Codex plan mode (Shift+Tab): Atlas proposes a plan and waits for
// approval before acting. Proposal card + the desktop proposal data.
// ─────────────────────────────────────────────────────────────
const DT_PROPOSAL = {
  summary: "I see a few ways to run this. Pick the one you want — or keep planning and I'll refine.",
  options: [
    {
      id: "cheapest",
      label: "Cheapest, flexible dates",
      tag: "from $382",
      body: "Widen the window to Nov 12–20 and sweep all three sources for refundable economy. Best fares route through ORD or DEN with one stop — you'd likely take a red-eye out and save ~$120 vs. nonstop. I'll flag any fare that needs a basic-economy downgrade so you can veto it.",
    },
    {
      id: "fastest",
      label: "Fastest, nonstop only",
      tag: "from $508",
      body: "Lock to your exact Nov 14–18 dates and only consider nonstops on United, JetBlue, and Delta. Total door-to-door time drops about 3h each way. Fewer seats at this price, so I'd hold the best one for 24h while you decide.",
    },
    {
      id: "flexible",
      label: "Most flexible, fully refundable",
      tag: "from $588",
      body: "Prioritize fully refundable, free-change fares even if a bit pricier — good if the trip might move. I'll prefer carriers where you have status and skip saver fares that block same-day changes.",
    },
  ],
};
const DTPlanBranchIcon = ({ size = 14 }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="9" width="6" height="6" rx="1.5"/>
    <rect x="15" y="4" width="6" height="6" rx="1.5"/>
    <rect x="15" y="14" width="6" height="6" rx="1.5"/>
    <path d="M9 12h3M12 7v10M12 7h3M12 17h3"/>
  </svg>
);

function DTPlanProposal({ proposal, approved, onApprove, onKeep }) {
  const [sel, setSel] = React.useState(proposal.options[0].id);
  const chosen = proposal.options.find((o) => o.id === sel) || proposal.options[0];
  return (
    <div className="dt-turn dt-turn-bro dt-turn-plan">
      <div className={`dt-planprop${approved ? " dt-planprop-on" : ""}`}>
        <div className="dt-planprop-head">
          <span className="dt-planprop-glyph" aria-hidden="true"><DTPlanBranchIcon size={15} /></span>
          <span className="dt-planprop-title">Proposed plans</span>
          <span className="dt-planprop-tag">{proposal.options.length} OPTIONS</span>
        </div>
        <p className="dt-planprop-summary">{proposal.summary}</p>
        <div className="dt-planopts" role="radiogroup" aria-label="Plan options">
          {proposal.options.map((o, i) => {
            const on = o.id === sel;
            return (
              <button
                key={o.id}
                type="button"
                role="radio"
                aria-checked={on}
                className={`dt-planopt${on ? " dt-planopt-on" : ""}`}
                onClick={() => !approved && setSel(o.id)}
                disabled={approved && !on}
              >
                <span className="dt-planopt-radio" aria-hidden="true" />
                <span className="dt-planopt-body">
                  <span className="dt-planopt-top">
                    <span className="dt-planopt-letter">{String.fromCharCode(65 + i)}</span>
                    <span className="dt-planopt-label">{o.label}</span>
                    {o.tag && <span className="dt-planopt-tag">{o.tag}</span>}
                  </span>
                  <span className="dt-planopt-text">{o.body}</span>
                </span>
              </button>
            );
          })}
        </div>
        {approved ? (
          <div className="dt-planprop-running">
            <span className="dt-planprop-running-spin" aria-hidden="true" />
            Running “{chosen.label}” — Atlas will report back
          </div>
        ) : (
          <div className="dt-planprop-actions">
            <button type="button" className="dt-planprop-approve" onClick={() => onApprove(chosen)}>
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12.5L10 18L20 6"/></svg>
              Approve &amp; run
            </button>
            <button type="button" className="dt-planprop-keep" onClick={onKeep}>Keep planning</button>
          </div>
        )}
      </div>
      <div className="dt-bubble-meta">{approved ? "Plan approved · executing" : "Pick a plan · awaiting your approval"}</div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// 4. BRO DETAIL — node offline
//    Optimized top notice: status said once, leads with the single
//    command most people need (restart on an already-set-up machine)
//    in the real dark-terminal style; full reinstall is tucked behind
//    a quiet disclosure.
// ─────────────────────────────────────────────────────────────
function DTOfflineNotice({ node = "Studio Mac", bro = "Atlas" }) {
  const RUN_CMD = "newbro executor run --token MRElL_T251_gUOuC";
  const INSTALL_CMD = "curl -fsSL newbro.dev/install.sh | sh";
  const [showReinstall, setShowReinstall] = React.useState(false);
  const [copied, setCopied] = React.useState(null); // 'run' | 'install' | null
  const timer = React.useRef(0);
  const copy = (key, text) => {
    try { navigator.clipboard && navigator.clipboard.writeText(text); } catch (e) {}
    setCopied(key);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(null), 1600);
  };
  const CopyBtn = ({ which, text }) => (
    <button
      type="button"
      className={`dt-offline-cmd-copy${copied === which ? " dt-offline-cmd-copy-done" : ""}`}
      onClick={() => copy(which, text)}
    >
      {copied === which ? (
        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12.5L10 18L20 6"/></svg>
      ) : (
        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>
      )}
      <span>{copied === which ? "Copied" : "Copy"}</span>
    </button>
  );
  return (
    <div className="dt-offline-notice">
      <div className="dt-offline-notice-head">
        <span className="dt-offline-notice-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M2 8.5a18 18 0 0 1 20 0"/>
            <path d="M5 12.5a13 13 0 0 1 14 0"/>
            <path d="M8.5 16a8 8 0 0 1 7 0"/>
            <circle cx="12" cy="20" r="0.9" fill="currentColor"/>
            <path d="M3 3l18 18"/>
          </svg>
        </span>
        <div className="dt-offline-notice-copy">
          <strong>{node} is offline</strong>
          <span>{bro} can&rsquo;t take new messages until this computer reconnects. Your draft is saved &mdash; the last turn retries on its own.</span>
        </div>
        <span className="dt-offline-notice-status" aria-hidden="true">
          <span className="dt-offline-notice-pip" />
          Auto-retrying
        </span>
      </div>

      <div className="dt-offline-cmd">
        <span className="dt-offline-cmd-prompt">$</span>
        <code className="dt-offline-cmd-line">newbro executor run <span className="dt-offline-cmd-tok">--token MRElL_T251_gUOuC</span></code>
        <CopyBtn which="run" text={RUN_CMD} />
      </div>

      <div className="dt-offline-foot">
        <span>Run on <strong>{node}</strong> to bring it back &mdash; it already has the CLI installed.</span>
        <button
          type="button"
          className="dt-offline-disclose"
          aria-expanded={showReinstall}
          onClick={() => setShowReinstall((v) => !v)}
        >
          <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M9 6l6 6-6 6"/></svg>
          {showReinstall ? "Hide reinstall" : "Reinstall or update the CLI"}
        </button>
      </div>

      {showReinstall && (
        <div className="dt-offline-reinstall">
          <p>CLI missing or out of date? This installs the latest and reconnects in one step:</p>
          <div className="dt-offline-cmd">
            <span className="dt-offline-cmd-prompt">$</span>
            <code className="dt-offline-cmd-line">curl -fsSL <span className="dt-offline-cmd-tok">newbro.dev/install.sh</span> | sh</code>
            <CopyBtn which="install" text={INSTALL_CMD} />
          </div>
        </div>
      )}
    </div>
  );
}
window.DTOfflineNotice = DTOfflineNotice;

// ─────────────────────────────────────────────────────────────
// 4b. BRO DETAIL — node offline (page)
// ─────────────────────────────────────────────────────────────
function BroDetailOfflineDesktop() {
  const [mode, setMode] = React.useState("ptt");
  return (
    <div className="dt-frame dt-shell">
      <DesktopHeader
        statusPill={<HeaderStatusPill status="paused" label="PAUSED · COMPUTER OFFLINE" />}
        broSwitch={
          <button type="button" className="dt-header-broswitch dt-header-broswitch-warn">
            <span className="dt-header-broswitch-avatar">
              <BroAvatar character="fox" state="offline" size={18} />
              <span className="dt-header-broswitch-pip" />
            </span>
            <span>Atlas</span>
            <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9l6 6 6-6"/></svg>
          </button>
        }
      />
      <main className="dt-detail-v2">
        <DTAgentActivity state="paused" />
        <section className="dt-pane">
          <div className="dt-pane-scroll">
            <div className="dt-pane-content">
              <DTOfflineNotice node="Studio Mac" bro="Atlas" />

              <div className="dt-thread-day"><span>Today · 14:22</span></div>

              <div className="dt-turn dt-turn-you">
                <div className="dt-bubble dt-bubble-you">
                  Compare three SFO → JFK options for Friday — red-eye okay.
                </div>
                <div className="dt-bubble-meta">Voice · 0:06 · transcribed · sent to Atlas</div>
              </div>

              <DTReasoningBubble done broName="Atlas" />

              <div className="dt-turn dt-turn-sys">
                <div className="dt-sys-event">
                  <span className="dt-sys-event-dot" />
                  <span><strong>Studio Mac</strong> went offline · 14:31</span>
                </div>
              </div>

              <div className="dt-turn dt-turn-you">
                <div className="dt-bubble dt-bubble-you dt-bubble-failed">
                  Yes, hold the Delta one if it's still under $480.
                </div>
                <div className="dt-bubble-meta dt-bubble-meta-failed">
                  <span className="dt-meta-failed-icon" aria-hidden="true">!</span>
                  <span>Not delivered · waiting for your computer</span>
                  <button type="button" className="dt-meta-retry">Retry when online</button>
                </div>
              </div>
            </div>
          </div>
          <DTComposerBar mode={mode} onMode={setMode} disabled broName="Atlas" />
        </section>
      </main>
    </div>
  );
}
window.BroDetailOfflineDesktop = BroDetailOfflineDesktop;

// ─────────────────────────────────────────────────────────────
// 5. HOME WITH BROS — full workbench, live crew
// ─────────────────────────────────────────────────────────────
const DT_HOME_BROS = [
  {
    id: "atlas",
    name: "Atlas",
    role: "Travel researcher",
    executor: "Codex",
    node: "Studio Mac",
    state: "working",
    task: "Compare SFO → JFK options for Friday",
    elapsed: "2m",
    progress: 64,
    step: "Pulling JetBlue fares",
    lastTurn: "2m ago",
    unread: 0,
  },
  {
    id: "forge",
    name: "Forge",
    role: "Operator",
    executor: "Hermes",
    node: "Workshop Mini",
    state: "working",
    task: "Draft Q2 booking sequence",
    elapsed: "5m",
    progress: 28,
    step: "Outlining steps",
    lastTurn: "5m ago",
    unread: 1,
  },
  {
    id: "muse",
    name: "Muse",
    role: "Planner",
    executor: "Codex",
    node: "Studio Mac",
    state: "idle",
    task: "Standing by — last spoke 1h ago",
    lastTurn: "1h ago",
  },
  {
    id: "scout",
    name: "Scout",
    role: "Availability checker",
    executor: "Hermes",
    node: "Travel Laptop",
    state: "offline",
    task: "Reconnecting…",
    lastTurn: "3h ago",
  },
];

function DTHomeChip({ state }) {
  const map = {
    working: { label: "WORKING", tone: "info" },
    idle:    { label: "STANDING BY", tone: "calm" },
    offline: { label: "OFFLINE", tone: "warn" },
  };
  const m = map[state] || map.idle;
  return (
    <span className={`dt-home-chip dt-home-chip-${m.tone}`}>
      <span className="dt-home-chip-dot" />
      {m.label}
    </span>
  );
}

function DTBroCard({ bro }) {
  const tone =
    bro.state === "working" ? "info" :
    bro.state === "offline" ? "warn" :
    "calm";
  const offline = bro.state === "offline";
  const working = bro.state === "working";
  const Tag = offline ? "div" : "button";
  return (
    <Tag type={offline ? undefined : "button"} className={`dt-bro-card dt-bro-card-${tone}${offline ? " dt-bro-card-offline" : ""}`}>
      <div className={`dt-bro-card-avatar dt-bro-card-avatar-${tone}`}>
        <BroAvatar character={broChar(bro.name)} state={bro.state === "working" ? "working" : bro.state === "offline" ? "offline" : "idle"} size={42} />
        {bro.unread > 0 && <span className="dt-bro-card-badge">{bro.unread}</span>}
      </div>
      <div className="dt-bro-card-body">
        <div className="dt-bro-card-row">
          <span className="dt-bro-card-name">{bro.name}</span>
          {!working && <DTHomeChip state={bro.state} />}
        </div>
        <div className="dt-bro-card-meta">
          <span className="dt-bro-card-mono">on {bro.executor}</span>
          <span className="dt-bro-meta-sep">·</span>
          <span className="dt-bro-card-mono">{bro.node}</span>
          {!working && (
            <React.Fragment>
              <span className="dt-bro-meta-sep">·</span>
              <span>{bro.lastTurn}</span>
            </React.Fragment>
          )}
        </div>
        {offline ? (
          <React.Fragment>
            <div className="dt-bro-card-task dt-bro-card-task-offline">
              <span className="dt-bro-card-task-text">{bro.node} dropped its connection — reconnect to resume.</span>
            </div>
            <div className="dt-bro-card-actions">
              <button type="button" className="dt-bro-card-connect" onClick={(e) => e.stopPropagation()}>
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M5 12h14M13 6l6 6-6 6"/>
                </svg>
                <span>Install &amp; connect</span>
              </button>
              <button type="button" className="dt-bro-card-open" onClick={(e) => e.stopPropagation()}>Open</button>
            </div>
          </React.Fragment>
        ) : (
          <div className={`dt-bro-card-task${bro.state === "working" ? " dt-bro-card-task-running" : ""}`}>
            {bro.state === "working" && <span className="dt-bro-card-spin" />}
            <span className="dt-bro-card-task-text">{bro.task}</span>
            {bro.state === "working" && (
              <span className="dt-bro-card-pct">running {bro.elapsed}</span>
            )}
          </div>
        )}
      </div>
      {!offline && <span className="dt-bro-card-arrow">›</span>}
    </Tag>
  );
}

const DT_RECENTS = [
  { title: "Compared SFO → JFK options", bro: "Atlas", when: "Today · 2m" },
  { title: "Drafted Q2 OKR review",     bro: "Forge", when: "Yesterday" },
  { title: "Pulled offsite venues",     bro: "Muse",  when: "Mon · 11:24" },
];

function DTRosterOffline({ bro }) {
  const INSTALL_CMD = `curl -fsSL newbro.dev/install.sh | sh -s -- --token MRElL_T251_gUOuC`;
  const [copied, setCopied] = React.useState(false);
  const t = React.useRef(0);
  const copy = (e) => {
    e.stopPropagation();
    try { navigator.clipboard && navigator.clipboard.writeText(INSTALL_CMD); } catch (err) {}
    setCopied(true);
    window.clearTimeout(t.current);
    t.current = window.setTimeout(() => setCopied(false), 1700);
  };
  return (
    <div className="dt-roster-row dt-roster-row-offline">
      <div className="dt-roster-avatar dt-roster-avatar-offline">
        <BroAvatar character={broChar(bro.name)} state="offline" size={26} />
      </div>
      <span className="dt-roster-name">{bro.name}</span>
      <span className="dt-roster-offline-note">{bro.node} offline · {bro.lastTurn}</span>
      <button
        type="button"
        className={`dt-roster-connect${copied ? " dt-roster-connect-done" : ""}`}
        onClick={copy}
        title="Copy the install + connect command"
      >
        {copied ? (
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12.5L10 18L20 6"/></svg>
        ) : (
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>
        )}
        <span>{copied ? "Copied" : "Copy install + connect"}</span>
      </button>
    </div>
  );
}

function HomeDesktop() {
  const working = DT_HOME_BROS.filter((b) => b.state === "working");
  const standby = DT_HOME_BROS.filter((b) => b.state !== "working");
  return (
    <div className="dt-frame dt-shell">
      <DesktopHeader statusPill={<HeaderStatusPill status="ready" label={`READY · ${working.length} of ${DT_HOME_BROS.length} working`} />} />
      <main className="dt-main">
        <div className="dt-main-pad dt-home-pad">
          <div className="dt-home-grid">
            <div className="dt-home-main">
              <header className="dt-page-head">
                <div>
                  <h1 className="dt-page-title">Home</h1>
                  <p className="dt-page-sub">
                    Hold space anywhere, talk to any bro, or open one to read their thread. Sessions persist as long as that computer stays online.
                  </p>
                </div>
                <div className="dt-page-actions">
                  <button type="button" className="dt-page-action dt-page-action-primary">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 5v14M5 12h14"/>
                    </svg>
                    <span>New bro</span>
                  </button>
                </div>
              </header>

              <section className="dt-home-section">
                <div className="dt-home-section-head">
                  <span className="ob-eyebrow ob-eyebrow-coral">IN FLIGHT · {working.length}</span>
                  <span className="dt-home-section-sub">Sessions currently dispatched</span>
                </div>
                <div className="dt-bro-grid">
                  {working.map((b) => (
                    <DTBroCard key={b.id} bro={b} />
                  ))}
                </div>
              </section>

              <section className="dt-home-section">
                <div className="dt-home-section-head">
                  <span className="ob-eyebrow">STANDING BY · {standby.length}</span>
                  <span className="dt-home-section-sub">Quiet for now — hold space to wake one</span>
                </div>
                <div className="dt-bro-roster">
                  {standby.map((b) => (
                    b.state === "offline" ? (
                      <DTRosterOffline key={b.id} bro={b} />
                    ) : (
                      <button key={b.id} type="button" className={`dt-roster-row dt-roster-row-${b.state}`}>
                        <div className={`dt-roster-avatar dt-roster-avatar-${b.state}`}>
                          <BroAvatar character={broChar(b.name)} state={b.state} size={26} />
                        </div>
                        <span className="dt-roster-name">{b.name}</span>
                        <span className="dt-roster-last">{bro_last(b)}</span>
                      </button>
                    )
                  ))}
                </div>
              </section>
            </div>

            <aside className="dt-home-rail">
              <section className="dt-rail-block">
                <div className="dt-rail-block-head">
                  <span className="ob-eyebrow">RECENT</span>
                  <button type="button" className="ob-link ob-link-sm">See all</button>
                </div>
                <ul className="dt-recent-list">
                  {DT_RECENTS.map((r, i) => (
                    <li key={i}>
                      <button type="button" className="dt-recent">
                        <span className="dt-recent-icon">
                          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>
                          </svg>
                        </span>
                        <span className="dt-recent-body">
                          <span className="dt-recent-title">{r.title}</span>
                          <span className="dt-recent-meta">
                            <span>{r.bro}</span>
                            <span className="dt-bro-meta-sep">·</span>
                            <span>{r.when}</span>
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            </aside>
          </div>
        </div>
      </main>
    </div>
  );
}

// Convert a bro's last-spoke into a tag.
function bro_last(b) {
  if (b.state === "idle")    return "spoke " + (b.lastTurn || "earlier");
  if (b.state === "offline") return (b.node || "node") + " · " + (b.lastTurn || "3h ago");
  return b.lastTurn || "";
}
window.HomeDesktop = HomeDesktop;

// ─────────────────────────────────────────────────────────────
// Desktop composer pieces — mode switch + 3 docks (PTT / Free / Text)
// Mirrors the mobile composer but uses the design system's
// signature coral hold-to-talk dock at desktop scale.
// ─────────────────────────────────────────────────────────────
const DT_MODE_ICONS = {
  ptt: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="3" width="6" height="12" rx="3"/>
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
    </svg>
  ),
  free: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="1.5" fill="currentColor"/>
      <path d="M8.5 8.5a5 5 0 0 0 0 7M15.5 8.5a5 5 0 0 1 0 7"/>
      <path d="M5.5 5.5a9 9 0 0 0 0 13M18.5 5.5a9 9 0 0 1 0 13"/>
    </svg>
  ),
  text: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="6" width="18" height="12" rx="2"/>
      <path d="M7 10h.01M11 10h.01M15 10h.01M7 14h10"/>
    </svg>
  ),
};

function DTModeSwitch({ value, onChange, disabled }) {
  const opts = [
    { v: "ptt",  label: "Push to talk" },
    { v: "free", label: "Free talk" },
    { v: "text", label: "Type" },
  ];
  return (
    <div className={`dt-modeswitch${disabled ? " dt-modeswitch-disabled" : ""}`} role="tablist">
      {opts.map((o) => {
        const on = value === o.v;
        return (
          <button
            key={o.v}
            type="button"
            role="tab"
            aria-selected={on}
            disabled={disabled}
            className={`dt-modeswitch-btn${on ? " dt-modeswitch-btn-on" : ""}`}
            onClick={() => !disabled && onChange(o.v)}
          >
            <span className="dt-modeswitch-icon">{DT_MODE_ICONS[o.v]}</span>
            <span className="dt-modeswitch-label">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function DTFreeSubToggle({ value, onChange, disabled }) {
  const isActive = value === "active";
  return (
    <div className={`dt-freesub${isActive ? " dt-freesub-active" : " dt-freesub-silent"}${disabled ? " dt-freesub-disabled" : ""}`}>
      <button
        type="button"
        role="switch"
        aria-checked={isActive}
        disabled={disabled}
        className="dt-freesub-track"
        onClick={() => !disabled && onChange(isActive ? "silent" : "active")}
      >
        <span className="dt-freesub-stop dt-freesub-stop-l">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
            <path d="M11 5L6 9H3v6h3l5 4z"/>
            <path d="M16 9l5 6M21 9l-5 6"/>
          </svg>
          <span>Quiet</span>
        </span>
        <span className="dt-freesub-thumb" aria-hidden="true" />
        <span className="dt-freesub-stop dt-freesub-stop-r">
          <span>Engaged</span>
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z"/>
          </svg>
        </span>
      </button>
      <span className="dt-freesub-caption">
        {isActive ? "Atlas may chime in mid-turn." : "Atlas listens, replies when you finish."}
      </span>
    </div>
  );
}

// PTT dock — the signature coral capsule. The single most recognisable
// newbro moment per the design system guide.
function DTPttDock({ disabled }) {
  return (
    <div className={`dt-ptt-wrap${disabled ? " dt-ptt-wrap-disabled" : ""}`}>
      <span className="dt-ptt-eyebrow">
        PRESS &amp; HOLD <kbd className="dt-kbd-light">SPACE</kbd> OR CLICK
      </span>
      <button type="button" className="dt-ptt-dock" disabled={disabled} aria-label="Hold to talk">
        <span className="dt-ptt-glow" aria-hidden="true" />
        <span className="dt-ptt-mic">
          {disabled ? (
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="3" width="6" height="12" rx="3"/>
              <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
              <path d="M3 3l18 18"/>
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="3" width="6" height="12" rx="3"/>
              <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
            </svg>
          )}
        </span>
        <span className="dt-ptt-label">{disabled ? "NODE OFFLINE" : "HOLD TO TALK"}</span>
      </button>
      <span className="dt-ptt-foot">
        {disabled
          ? "Reconnect Studio Mac to start a new turn."
          : "Audio is sent directly — no transcript stored."}
      </span>
    </div>
  );
}

function DTFreeDock({ subMode, onSubChange, disabled }) {
  return (
    <div className={`dt-free-wrap${disabled ? " dt-free-wrap-disabled" : ""}`}>
      <DTFreeSubToggle value={subMode} onChange={onSubChange} disabled={disabled} />
      <button type="button" className={`dt-free-dock dt-free-dock-${subMode}`} disabled={disabled}>
        <span className={`dt-free-led dt-free-led-${subMode}`} />
        <span className="dt-free-text">
          <span className="dt-free-title">
            {disabled ? "Channel paused" : `Open channel · ${subMode === "silent" ? "Quiet" : "Engaged"}`}
          </span>
          <span className="dt-free-sub">
            {disabled
              ? "Studio Mac is offline."
              : subMode === "silent"
                ? "Atlas replies when you finish."
                : "Atlas may chime in mid-turn."}
          </span>
        </span>
        <span className="dt-free-waves" aria-hidden="true">
          {Array.from({ length: 22 }).map((_, i) => {
            const h = 4 + Math.abs(Math.sin((i + 1) * 0.55)) * 10;
            return <i key={i} style={{ height: h }} />;
          })}
        </span>
      </button>
    </div>
  );
}

function DTTextDock({ disabled }) {
  return (
    <div className={`dt-text-wrap${disabled ? " dt-text-wrap-disabled" : ""}`}>
      <div className="dt-text-dock">
        <span className="dt-text-prompt">›</span>
        <input
          type="text"
          placeholder={disabled
            ? "Sending paused while Studio Mac is offline…"
            : "Tell Atlas what to do next — Enter to send."}
          disabled={disabled}
        />
        <button type="button" className="dt-text-send" disabled={disabled} aria-label="Send">
          <span>Send</span>
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12h14M13 6l6 6-6 6"/>
          </svg>
        </button>
      </div>
      <span className="dt-text-foot">
        <kbd className="dt-kbd">↵</kbd> to send · <kbd className="dt-kbd">⇧↵</kbd> for newline
      </span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Side rail for the detail pages — Artifacts + other Threads.
// We only see what the agent says back, so this is what's
// genuinely useful next to the conversation.
// ─────────────────────────────────────────────────────────────
function DTAgentActivity({ state }) {
  // state: 'live' | 'paused'
  const live = state === "live";

  // Other threads with this bro.
  const threads = [
    { id: "t04", title: "SFO → JFK options",            when: "today · live",    n: 4, on: true },
    { id: "t03", title: "Hotel near Bryant Park",        when: "yesterday",       n: 9 },
    { id: "t02", title: "Tokyo May itinerary",           when: "Mon · 11:24",     n: 22 },
    { id: "t01", title: "PEK ↔ SFO award alternatives",  when: "May 12",          n: 11 },
  ];

  return (
    <aside className="dt-activity">
      <section className="dt-activity-block">
        <div className="dt-activity-block-head">
          <span className="ob-eyebrow">THREADS WITH ATLAS · {threads.length}</span>
        </div>
        <ul className="dt-threadlist">
          {threads.map((t) => (
            <li key={t.id}>
              <button type="button" className={`dt-threadlist-row${t.on ? " dt-threadlist-row-on" : ""}`}>
                <span className="dt-threadlist-body">
                  <span className="dt-threadlist-title">{t.title}</span>
                  <span className="dt-threadlist-meta">
                    <span>{t.when}</span>
                    <span className="dt-bro-meta-sep">·</span>
                    <span>{t.n} turns</span>
                  </span>
                </span>
                {t.on && live  && <span className="dt-threadlist-pip" />}
                {t.on && !live && <span className="dt-threadlist-pip dt-threadlist-pip-paused" />}
              </button>
            </li>
          ))}
        </ul>
        <button type="button" className="dt-thread-new">
          <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 5v14M5 12h14"/>
          </svg>
          <span>New thread with Atlas</span>
        </button>
      </section>
    </aside>
  );
}
// ─────────────────────────────────────────────────────────────
// DTReasoningBubble — the agent's live reasoning stream. A single
// blue bubble whose body keeps updating as the agent runs multiple
// executions; each update is appended as a new line, the latest one
// stays "active" while it works. No determinate progress (%, ETA).
// ─────────────────────────────────────────────────────────────
const DT_REASONING = {
  steps: [
    { kind: "act",   tool: "flights.search", text: "Querying Friday SFO → JFK fares across United, Delta, and JetBlue." },
    { kind: "think", text: "United's best is a $452 red-eye — 11:05p out, one stop via DEN." },
    { kind: "think", text: "Delta runs a $468 non-stop, 9:40p departure into JFK 6:18a Saturday." },
    { kind: "act",   tool: "fares.rules", text: "Reading fare rules — JetBlue's $419 red-eye is basic-economy only. Flagging it for your veto." },
    { kind: "think", text: "Ranking the three on price against total door-to-door time…" },
  ],
  answer:
    "Three solid options. Delta's $468 non-stop is the best balance — 9:40p out, into JFK 6:18a Saturday. United's $452 red-eye saves a little but adds a DEN stop, and JetBlue is cheapest at $419 yet basic-economy only. Want me to hold the Delta seat?",
};

// done=true renders straight to the settled state — used for history /
// already-finished turns, which never replay the live reasoning stream.
function DTReasoningBubble({ data = DT_REASONING, broName = "Atlas", done = false }) {
  // normalize steps to objects so older string-based callers still work
  const steps = data.steps.map((s) => (typeof s === "string" ? { kind: "think", text: s } : s));

  // ── display tweaks (from shared voice context, defaulted on) ──
  const v = (typeof useVoice === "function") ? useVoice() : null;
  const instant = v ? v.msgInstant : true;  // instant skeleton before first line
  const marks   = v ? v.msgMarks   : true;  // distinguish tool actions
  const steer   = v ? v.msgSteer   : true;  // show Stop / Steer on live bubble

  // phase: "ack" (instant skeleton) → "streaming" → "done"
  const [phase, setPhase] = React.useState(done ? "done" : (instant ? "ack" : "streaming"));
  const [shown, setShown] = React.useState(done ? steps.length : (instant ? 0 : 1));
  const [open, setOpen] = React.useState(false); // expand collapsed reasoning
  const [stopped, setStopped] = React.useState(false);

  // Replay the live stream whenever a treatment tweak flips, so toggling a
  // control in the panel immediately shows its effect (demo affordance).
  const firstRun = React.useRef(true);
  React.useEffect(() => {
    if (done) return;
    if (firstRun.current) { firstRun.current = false; return; }
    setStopped(false);
    setOpen(false);
    setPhase(instant ? "ack" : "streaming");
    setShown(instant ? 0 : 1);
  }, [instant, marks, steer, done]);

  // brief acknowledged beat — the bubble is on screen instantly with a
  // shimmer skeleton, then the first real line lands.
  React.useEffect(() => {
    if (phase !== "ack") return;
    const id = setTimeout(() => { setPhase("streaming"); setShown(1); }, 780);
    return () => clearTimeout(id);
  }, [phase]);

  // Reveal one execution line at a time while streaming.
  React.useEffect(() => {
    if (phase !== "streaming" || stopped || shown >= steps.length) return;
    const id = setTimeout(() => setShown((n) => Math.min(n + 1, steps.length)), 1900);
    return () => clearTimeout(id);
  }, [phase, shown, steps.length, stopped]);

  // Once every line has streamed, settle into the done state and drop the
  // live progress entirely.
  React.useEffect(() => {
    if (phase !== "streaming" || stopped || shown < steps.length) return;
    const id = setTimeout(() => setPhase("done"), 1500);
    return () => clearTimeout(id);
  }, [phase, shown, steps.length, stopped]);

  // Demo loop: this is a review artboard, so the live loading status would
  // otherwise only play once on mount and be gone before you look. After the
  // bubble settles, dwell on the answer a beat, then replay the whole turn.
  // (Skipped for history bubbles and when the user has stopped the stream.)
  React.useEffect(() => {
    if (done || phase !== "done" || stopped) return;
    const id = setTimeout(() => {
      setOpen(false);
      setPhase(instant ? "ack" : "streaming");
      setShown(instant ? 0 : 1);
    }, 4200);
    return () => clearTimeout(id);
  }, [done, phase, stopped, instant]);

  // shared renderer for a single step line (live + history)
  const renderMark = (st) => {
    if (marks && st.kind === "act") {
      return (
        <span className="dt-reason-step-mark dt-reason-step-mark-act" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="9" height="9" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4l-6 6a1.5 1.5 0 0 0 2.1 2.1l6-6a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.1-2.1z"/>
          </svg>
        </span>
      );
    }
    return <span className="dt-reason-step-mark" aria-hidden="true" />;
  };
  const renderText = (st) => (
    <span className="dt-reason-step-text">
      {marks && st.kind === "act" && st.tool && (
        <span className="dt-reason-tool">{st.tool}</span>
      )}
      {st.text}
    </span>
  );

  // ── DONE / HISTORY ── no reasoning progress; final answer + a tucked-away
  // "Reasoned" toggle the user can expand on demand.
  if (phase === "done") {
    return (
      <div className="dt-turn dt-turn-bro">
        <div className="dt-bubble dt-bubble-bro dt-bubble-answer">
          <button
            type="button"
            className={`dt-reason-collapsed${open ? " dt-reason-collapsed-open" : ""}`}
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
          >
            <svg className="dt-reason-collapsed-check" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M4 12.5L10 18L20 6"/>
            </svg>
            <span>{open ? "Hide reasoning" : "Reasoned"}</span>
            <svg className="dt-reason-collapsed-chev" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M6 9l6 6 6-6"/>
            </svg>
          </button>
          {open && (
            <ol className="dt-reason-steps dt-reason-steps-static">
              {steps.map((s, i) => (
                <li key={i} className="dt-reason-step dt-reason-step-done">
                  {renderMark(s)}
                  {renderText(s)}
                </li>
              ))}
            </ol>
          )}
          <span className="dt-answer-text">{data.answer}</span>
        </div>
        <div className="dt-bubble-meta">{broName} · 14:24</div>
      </div>
    );
  }

  // ── ACK ── bubble is on screen instantly; shimmer skeleton, no lines yet.
  if (phase === "ack") {
    return (
      <div className="dt-turn dt-turn-bro">
        <div className="dt-bubble dt-bubble-bro dt-bubble-reason">
          <span className="dt-reason-kicker">
            <span className="dt-reason-orb" aria-hidden="true"><span /><span /><span /></span>
            {broName} is reasoning
          </span>
          <div className="dt-reason-skeleton" aria-hidden="true">
            <span style={{ width: "82%" }} />
            <span style={{ width: "61%" }} />
          </div>
        </div>
        <div className="dt-bubble-meta">{broName} · starting up · 14:22</div>
      </div>
    );
  }

  // ── STREAMING ── live reasoning; newest line + last 3 rounds, older faded.
  const WINDOW = 4;
  const start = Math.max(0, shown - WINDOW);
  const visible = steps.slice(start, shown);
  const FADE = [1, 0.74, 0.46, 0.2]; // by distance from the newest line

  return (
    <div className="dt-turn dt-turn-bro">
      <div className="dt-bubble dt-bubble-bro dt-bubble-reason">
        <span className="dt-reason-kicker">
          <span className="dt-reason-orb" aria-hidden="true">
            <span /><span /><span />
          </span>
          {stopped ? `${broName} stopped` : `${broName} is reasoning`}
        </span>
        <ol className="dt-reason-steps">
          {visible.map((s, j) => {
            const idx = start + j;
            const dist = visible.length - 1 - j; // 0 = newest
            const isLast = dist === 0;
            return (
              <li
                key={idx}
                className={`dt-reason-step${isLast && !stopped ? " dt-reason-step-active" : " dt-reason-step-done"}${marks && s.kind === "act" ? " dt-reason-step-act" : ""}`}
                style={{ opacity: FADE[dist] ?? 0.2 }}
              >
                {renderMark(s)}
                {renderText(s)}
              </li>
            );
          })}
        </ol>
        {steer && !stopped && (
          <div className="dt-reason-steer">
            <button type="button" className="dt-reason-steer-btn dt-reason-steer-stop" onClick={() => setStopped(true)}>
              <svg viewBox="0 0 24 24" width="11" height="11" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2.5"/></svg>
              Stop
            </button>
            <span className="dt-reason-steer-hint">Hold <kbd className="dt-kbd">Space</kbd> to interrupt</span>
          </div>
        )}
        {steer && stopped && (
          <div className="dt-reason-steer dt-reason-steer-stopped">
            <span className="dt-reason-steer-stoptag">Stopped — say what to change and {broName} picks back up.</span>
            <button type="button" className="dt-reason-steer-btn dt-reason-steer-resume" onClick={() => setStopped(false)}>
              <svg viewBox="0 0 24 24" width="11" height="11" fill="currentColor" aria-hidden="true"><path d="M7 5l11 7-11 7z"/></svg>
              Resume
            </button>
          </div>
        )}
      </div>
      <div className="dt-bubble-meta">{broName} · {stopped ? "paused by you" : "updating live"} · 14:22</div>
    </div>
  );
}

function BroDetailActiveDesktop({ initialPlanMode = false, initialProposal = false } = {}) {
  const [mode, setMode] = React.useState("ptt");
  const [planMode, setPlanMode] = React.useState(initialPlanMode);
  const [proposal, setProposal] = React.useState(initialProposal);
  const [approved, setApproved] = React.useState(false);
  const [planTurn, setPlanTurn] = React.useState(
    initialProposal ? "Find me SFO → JFK options for Nov 14–18, under $500 round-trip." : null
  );
  const sendPlan = (text) => { setPlanTurn(text); setProposal(true); setApproved(false); };
  const approvePlan = () => { setApproved(true); setPlanMode(false); };
  return (
    <div className="dt-frame dt-shell">
      <DesktopHeader
        statusPill={<HeaderStatusPill status="live" label="LIVE · LISTENING" />}
        broSwitch={
          <button type="button" className="dt-header-broswitch dt-header-broswitch-info">
            <span className="dt-header-broswitch-avatar">
              <BroAvatar character="fox" state="working" size={18} />
              <span className="dt-header-broswitch-pip" />
            </span>
            <span>Atlas</span>
            <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9l6 6 6-6"/></svg>
          </button>
        }
      />
      <main className="dt-detail-v2">
        <DTAgentActivity state="live" />
        <section className="dt-pane">
          <div className="dt-pane-scroll">
            <div className="dt-pane-content">
              <div className="dt-thread-day"><span>Today · 14:22</span></div>

              {proposal ? (
                <React.Fragment>
                  {planTurn && (
                    <div className="dt-turn dt-turn-you">
                      <span className="dt-plantag" aria-label="Sent in plan mode">
                        <DTPlanBranchIcon size={11} />
                        Plan mode
                      </span>
                      <div className="dt-bubble dt-bubble-you dt-bubble-plan">{planTurn}</div>
                      <div className="dt-bubble-meta">Plan request · just now</div>
                    </div>
                  )}
                  <DTPlanProposal
                    proposal={DT_PROPOSAL}
                    approved={approved}
                    onApprove={approvePlan}
                    onKeep={() => setProposal(true)}
                  />
                </React.Fragment>
              ) : (
                <React.Fragment>
                  <div className="dt-turn dt-turn-you">
                    <div className="dt-bubble dt-bubble-you">
                      Compare three SFO → JFK options for Friday — red-eye okay.
                    </div>
                    <div className="dt-bubble-meta">Voice · 0:06 · transcribed · sent to Atlas</div>
                  </div>

                  <DTReasoningBubble broName="Atlas" />
                </React.Fragment>
              )}
            </div>
          </div>
          <DTComposerBar
            mode={mode}
            onMode={setMode}
            broName="Atlas"
            planMode={planMode}
            onTogglePlan={() => setPlanMode((o) => !o)}
            onSendPlan={sendPlan}
          />
        </section>
      </main>
    </div>
  );
}
window.BroDetailActiveDesktop = BroDetailActiveDesktop;
