/* variants-mobile.jsx — Three mobile-first voice interaction designs.
 *
 *   1. HALO    — voice-call vibe; big bro halo + thumb-zone orb
 *   2. THREADS — iMessage-like thread of turns + composer bar
 *   3. CONSOLE — operator panel; transcript log + dense bottom controls
 *
 * All three subscribe to the same shared VoiceContext as the desktop
 * variants and respect inputMode (ptt / free / text).
 */

// ═════════════════════════════════════════════════════════════
// shared bits
// ═════════════════════════════════════════════════════════════
const M_BRO = { name: "Atlas", role: "Travel researcher", node: "Studio Mac", executor: "Codex" };

// ── Coding-agent controls (Codex only) ────────────────────────
//   PLAN — "plan mode" (⇧⇥ on desktop): Atlas researches and drafts
//          a few candidate approaches, then WAITS for you to pick one
//          and approve before acting.
const ATLAS_PROPOSAL = {
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

const stateMeta = {
  idle:      { label: "Standby",     tone: "calm",  short: "standby" },
  listening: { label: "Listening",   tone: "live",  short: "listening" },
  thinking:  { label: "Drafting",    tone: "warm",  short: "drafting" },
  working:   { label: "Working",     tone: "info",  short: "working" },
  reporting: { label: "Just heard",  tone: "live",  short: "ready"   },
  error:     { label: "Reconnecting",tone: "warn",  short: "paused"   },
};

// Procedural fox portrait scaled to a given size
function MobileFox({ size = 80, mode = "idle" }) {
  const tone = stateMeta[mode].tone;
  const stroke = tone === "live" ? "#10b981"
              : tone === "warm" ? "#ff6a3d"
              : tone === "info" ? "#3b82f6"
              : tone === "warn" ? "#b45309" : "#6b7280";
  return (
    <svg viewBox="0 0 160 160" width={size} height={size} fill="none">
      <path d="M40 70 L60 38 L74 70" stroke={stroke} strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M86 70 L100 38 L120 70" stroke={stroke} strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M36 92 Q36 56 80 56 Q124 56 124 92 Q124 128 80 128 Q36 128 36 92 Z" stroke={stroke} strokeWidth="2.6"/>
      <circle cx="64" cy="90" r="2.6" fill={stroke}/>
      <circle cx="96" cy="90" r="2.6" fill={stroke}/>
      {mode === "reporting" ? (
        <path d="M68 104 Q80 114 92 104" stroke={stroke} strokeWidth="2.3" strokeLinecap="round" fill="none"/>
      ) : mode === "listening" ? (
        <ellipse cx="80" cy="106" rx="6" ry="3.5" stroke={stroke} strokeWidth="2.3" fill="none"/>
      ) : (
        <path d="M70 106 L82 102 L92 106" stroke={stroke} strokeWidth="2.3" strokeLinecap="round" fill="none" strokeLinejoin="round"/>
      )}
    </svg>
  );
}

// The actual Newbro mascot. Renders the logo image inside a circular
// tile that tints/glows according to the current voice mode. The image
// itself doesn't change color — only the backdrop does — keeping the
// mascot recognizable across all states.
function Mascot({ size = 80, mode = "idle", crop = 1.18 }) {
  const tone = stateMeta[mode].tone;
  const innerSize = Math.round(size * crop);
  return (
    <div
      className={`mascot mascot-${tone}`}
      style={{ width: size, height: size }}
    >
      <img
        src="assets/newbro-logo.webp"
        alt="Atlas"
        style={{ width: innerSize, height: innerSize, marginLeft: (size - innerSize) / 2, marginTop: (size - innerSize) / 2 }}
        draggable={false}
      />
    </div>
  );
}

// Mode-switch icons — small, 16px, stroke-only
const ModeIcons = {
  ptt: (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="3" width="6" height="12" rx="3"/>
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
    </svg>
  ),
  free: (
    // broadcast / open-channel — concentric arcs
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="1.5" fill="currentColor"/>
      <path d="M8.5 8.5a5 5 0 0 0 0 7M15.5 8.5a5 5 0 0 1 0 7"/>
      <path d="M5.5 5.5a9 9 0 0 0 0 13M18.5 5.5a9 9 0 0 1 0 13"/>
    </svg>
  ),
  text: (
    // keyboard
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="6" width="18" height="12" rx="2"/>
      <path d="M7 10h.01M11 10h.01M15 10h.01M7 14h10"/>
    </svg>
  ),
};

// Two-mode segmented control — matches the desktop model.
//   "ptt"  — push-to-talk (and typing alongside, in chat threads).
//   "free" — open channel, voice only.
// The expanding-active-tab feel is preserved: inactive segment shows icon
// only, active expands to icon + label with a sliding indicator behind it.
function MobileModeSwitch({ value, onChange, theme = "light" }) {
  // Coerce legacy "text" inputMode back to "ptt" — typing is now merged.
  const v = value === "text" ? "ptt" : value;
  const options = [
    { v: "ptt",  label: "Tap to send" },
    { v: "free", label: "Always on" },
  ];
  return (
    <div className={`mob-mode mob-mode-${theme}`} role="tablist" aria-label="Input mode">
      {options.map((o) => {
        const on = v === o.v;
        return (
          <button
            key={o.v}
            type="button"
            role="tab"
            aria-selected={on}
            className={`mob-mode-btn${on ? " mob-mode-btn-on" : ""}`}
            onClick={() => onChange(o.v)}
            title={o.label}
          >
            <span className="mob-mode-icon">{ModeIcons[o.v]}</span>
            <span className="mob-mode-label">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function formatDuration(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  return `0:${String(s).padStart(2, "0")}`;
}

// ─────────────────────────────────────────────────────────────
// MobileBroWheel — radio-dial bro switcher.
// Borrowed from the "walkie" concept but stripped down: no router
// channel, no character glyphs. Just letter avatars + state pips,
// with a thin coral dial bezel underneath.
// ─────────────────────────────────────────────────────────────
const M_WHEEL_W = 88;
const M_WHEEL_INITIAL_TONES = {
  // tile bg / ink colors per bro — keeps them distinguishable at
  // letter-avatar scale without going full-character.
  Atlas: { bg: "#fff0e9", ink: "#ff6a3d" },
  Forge: { bg: "#e9f7ff", ink: "#1d6fb8" },
  Muse:  { bg: "#f0ecff", ink: "#6b4ce6" },
  Scout: { bg: "#fff7d9", ink: "#a26b13" },
};
function MobileBroWheel({ bros, activeId, onSelect }) {
  const idx = Math.max(0, bros.findIndex((b) => b.id === activeId));
  return (
    <div className="mob-wheel">
      <div className="mob-wheel-fade mob-wheel-fade-l" aria-hidden="true" />
      <div className="mob-wheel-fade mob-wheel-fade-r" aria-hidden="true" />
      <div className="mob-wheel-track">
        <div
          className="mob-wheel-row"
          style={{ transform: `translateX(calc(50% - ${(idx + 0.5) * M_WHEEL_W}px))` }}
        >
          {bros.map((b, i) => {
            const dist = Math.abs(i - idx);
            const op = Math.max(0.32, 1 - dist * 0.32);
            const sc = Math.max(0.82, 1 - dist * 0.08);
            const on = dist === 0;
            const tone = M_WHEEL_INITIAL_TONES[b.name] || { bg: "#f0f0f0", ink: "#5b5e64" };
            return (
              <button
                key={b.id}
                type="button"
                className={`mob-wheel-item${on ? " mob-wheel-item-on" : ""}`}
                style={{ width: M_WHEEL_W, opacity: op, transform: `scale(${sc})` }}
                onClick={() => onSelect(b.id)}
              >
                <div
                  className={`mob-wheel-tile mob-wheel-tile-${b.state}${on ? " mob-wheel-tile-on" : ""}`}
                  style={{ background: tone.bg, color: tone.ink }}
                >
                  <span className="mob-wheel-initial">{b.name[0]}</span>
                  {b.state === "working" && <span className="mob-wheel-pip mob-wheel-pip-live" />}
                  {b.state === "offline" && <span className="mob-wheel-pip mob-wheel-pip-warn" />}
                  {b.unread > 0 && (
                    <span className="mob-wheel-badge">{b.unread}</span>
                  )}
                </div>
                <span className={`mob-wheel-name${on ? " mob-wheel-name-on" : ""}`}>{b.name}</span>
              </button>
            );
          })}
        </div>
      </div>
      <MobileWheelDial />
    </div>
  );
}

function MobileWheelDial() {
  const ticks = 33;
  return (
    <div className="mob-wheel-dial">
      <svg width="100%" height="10" viewBox="-100 0 200 10" preserveAspectRatio="none">
        {Array.from({ length: ticks }).map((_, i) => {
          const off = i - (ticks - 1) / 2;
          const x = off * 6;
          const major = i % 4 === 0;
          const center = i === (ticks - 1) / 2;
          return (
            <line
              key={i}
              x1={x} y1={center ? 0 : major ? 3 : 5}
              x2={x} y2={9}
              stroke={center ? "var(--nb-coral)" : major ? "var(--nb-ink-muted)" : "var(--nb-line)"}
              strokeWidth={center ? 1.4 : 0.6}
              strokeLinecap="round"
            />
          );
        })}
      </svg>
      <svg width="10" height="6" className="mob-wheel-dial-arrow">
        <path d="M5 6 L1 0 L9 0 Z" fill="var(--nb-coral)" />
      </svg>
    </div>
  );
}

// Free-mode response-style picker — a tactile slider rather than two flat
// buttons. The thumb slides between "Quiet" and "Engaged" stops; the track
// shifts color (amber → green) and a small preview line below explains how
// the bro will behave.
function FreeSubToggle({ value, onChange, theme = "light" }) {
  const isActive = value === "active";
  const preview = isActive
    ? "Atlas may chime in mid-turn"
    : "Atlas listens, replies when you finish";
  return (
    <div className={`free-sub free-sub-${theme}${isActive ? " free-sub-active" : " free-sub-silent"}`}>
      <button
        type="button"
        className="free-sub-track"
        onClick={(e) => { e.stopPropagation(); onChange(isActive ? "silent" : "active"); }}
        role="switch"
        aria-checked={isActive}
        aria-label={isActive ? "Active mode" : "Silent mode"}
      >
        <span className="free-sub-stop free-sub-stop-l">
          <span className="free-sub-glyph">
            {/* "shh" — muted speaker */}
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
              <path d="M11 5L6 9H3v6h3l5 4z"/>
              <path d="M16 9l5 6M21 9l-5 6"/>
            </svg>
          </span>
          <span className="free-sub-stop-label">Quiet</span>
        </span>
        <span className="free-sub-thumb" aria-hidden="true">
          <span className="free-sub-thumb-dot" />
        </span>
        <span className="free-sub-stop free-sub-stop-r">
          <span className="free-sub-stop-label">Engaged</span>
          <span className="free-sub-glyph">
            {/* talking — message bubble */}
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z"/>
            </svg>
          </span>
        </span>
      </button>
      <div className="free-sub-preview">{preview}</div>
    </div>
  );
}

// Audio-message bubble — used for PTT turns (no transcript shown).
// Pure waveform thumbnail + duration + play button.
function AudioBubble({ duration, kind = "you", live = false }) {
  const bars = Array.from({ length: 36 });
  const dur = formatDuration(duration);
  return (
    <div className={`audio-bubble audio-bubble-${kind}${live ? " audio-bubble-live" : ""}`}>
      <span className="audio-bubble-play">
        {live ? (
          <span className="audio-bubble-rec">REC</span>
        ) : (
          <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
            <path d="M8 5v14l11-7z"/>
          </svg>
        )}
      </span>
      <span className="audio-bubble-wave">
        {bars.map((_, i) => {
          const h = 4 + Math.abs(Math.sin((i + 1) * 0.55)) * 12;
          return <i key={i} style={{ height: h }} />;
        })}
      </span>
      <span className="audio-bubble-dur">{dur}</span>
    </div>
  );
}

// Threads text composer — clean iMessage-style pill with inline send.
// Suggestion chips scroll above the input. The send button lives inside
// the text pill and only colors up when there's content.
function ThrTextComposer({ value, onChange, onSend, disabled }) {
  const taRef = React.useRef(null);
  // Auto-grow with content (capped)
  React.useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "0";
    ta.style.height = Math.min(ta.scrollHeight, 100) + "px";
  }, [value]);

  const suggestions = [
    "Continue from the JFK shortlist",
    "What if I leave Saturday instead?",
    "Hold the first one",
  ];
  const showSuggestions = !value.trim() && !disabled;
  const hasContent = value.trim().length > 0;

  return (
    <div className="thr-text-composer">
      {showSuggestions && (
        <div className="thr-suggest">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              className="thr-suggest-chip"
              onClick={() => onSend(s)}
            >
              {s}
            </button>
          ))}
        </div>
      )}
      <div className="thr-text-row">
        <button type="button" className="thr-text-attach" aria-label="Attach">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 5v14M5 12h14"/>
          </svg>
        </button>
        <div className={`thr-text-pill${hasContent ? " thr-text-pill-on" : ""}`}>
          <textarea
            ref={taRef}
            rows={1}
            placeholder="Message"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSend(value);
              }
            }}
            disabled={disabled}
          />
          <button
            type="button"
            className={`thr-text-send${hasContent ? " thr-text-send-on" : ""}`}
            onClick={() => onSend(value)}
            disabled={disabled || !hasContent}
            aria-label="Send"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 19V5M5 12l7-7 7 7"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════
// HOME — bros list / workspace overview. Lives alongside the chat
// thread; tapping a bro would navigate INTO a thread in a real app.
// ═════════════════════════════════════════════════════════════
const HOME_BROS = [
  {
    id: "atlas",
    name: "Atlas",
    executor: "Codex",
    state: "working",
    node: "Studio Mac",
    task: "Compare SFO → JFK options",
    elapsed: "2m",
    lastTurn: "2m",
    unread: 0,
  },
  {
    id: "forge",
    name: "Forge",
    executor: "Hermes",
    state: "working",
    node: "Workshop Mini",
    task: "Draft booking sequence",
    elapsed: "5m",
    lastTurn: "5m",
    unread: 1,
  },
  {
    id: "muse",
    name: "Muse",
    executor: "ACPX",
    state: "idle",
    node: null,
    task: "Standing by · unbound",
    lastTurn: "1h",
    unread: 0,
  },
  {
    id: "scout",
    name: "Scout",
    executor: "Mock",
    state: "offline",
    node: "Travel Laptop",
    task: "Reconnecting…",
    lastTurn: "3h",
    unread: 0,
  },
];

const HOME_RECENTS = [
  { id: "r1", title: "Compared three SFO → JFK options", bro: "Atlas", when: "Today · 2m ago", artifact: "sfo-jfk-fri.csv" },
  { id: "r2", title: "Drafted Q2 OKR review",         bro: "Forge", when: "Yesterday",        artifact: "okr-q2-review.md" },
  { id: "r3", title: "Pulled offsite venue options",  bro: "Muse",  when: "Mon · 11:24",       artifact: "venues.md" },
];

function HomeStateChip({ state, working }) {
  // Compact pill: "working", "standing by", "offline". The % lives on the
  // progress bar; chip just names the state.
  const tone =
    state === "working" ? "info" :
    state === "idle"    ? "calm" :
    state === "offline" ? "warn" :
    state === "live"    ? "live" : "calm";
  const label =
    state === "working" ? "working" :
    state === "idle"    ? "standing by" :
    state === "offline" ? "offline" :
    state === "live"    ? "live" : state;
  return (
    <span className={`home-chip home-chip-${tone}`}>
      <span className="home-chip-dot" />
      {label}
    </span>
  );
}

function HomeBroCard({ bro, onOpen, featured }) {
  const tone =
    bro.state === "working" ? "info" :
    bro.state === "offline" ? "warn" :
    "calm";
  if (!featured) {
    // compact row for non-working bros
    return (
      <button type="button" className="home-row" onClick={onOpen}>
        <div className={`home-row-avatar home-row-avatar-${tone}`}>
          <Mascot size={42} mode={bro.state === "working" ? "working" : "idle"} crop={1.0} />
        </div>
        <div className="home-row-body">
          <div className="home-row-top">
            <span className="home-row-name">{bro.name}</span>
            <span className="home-row-role">· on {bro.executor}</span>
          </div>
          <div className="home-row-task">{bro.task}</div>
        </div>
        <div className="home-row-right">
          <HomeStateChip state={bro.state} />
          <span className="home-row-when">{bro.lastTurn}</span>
        </div>
      </button>
    );
  }
  return (
    <button type="button" className={`home-card home-card-${tone}`} onClick={onOpen}>
      <div className="home-card-head">
        <div className={`home-card-avatar home-card-avatar-${tone}`}>
          <Mascot size={48} mode={bro.state === "working" ? "working" : "idle"} crop={1.0} />
          {bro.unread > 0 && <span className="home-card-badge">{bro.unread}</span>}
        </div>
        <div className="home-card-headtext">
          <div className="home-card-name">
            {bro.name}
            <span className="home-card-role">· on {bro.executor}</span>
          </div>
          <div className="home-card-meta">
            <HomeStateChip state={bro.state} />
            <span className="home-card-node">{bro.node}</span>
          </div>
        </div>
        <span className="home-card-arrow">›</span>
      </div>
      <div className={`home-card-task${bro.state === "working" ? " home-card-task-running" : ""}`}>
        {bro.state === "working" && <span className="home-card-spin" aria-hidden="true" />}
        <span className="home-card-task-text">{bro.task}</span>
        {bro.state === "working" && <span className="home-card-task-meta">running {bro.elapsed}</span>}
      </div>
    </button>
  );
}

// ─────────────────────────────────────────────────────────────
// Bro card variants for EDIT mode — wraps the existing card/row
// with an iOS-style remove badge in the top-left corner. We keep
// the cards otherwise pristine so swapping in/out of edit mode is
// just a class change.
// ─────────────────────────────────────────────────────────────
function HomeBroEditable({ bro, featured, editing, onRemove, onOpen }) {
  return (
    <div className={`home-edit-wrap${editing ? " home-edit-wrap-on" : ""}${featured ? " home-edit-wrap-card" : " home-edit-wrap-row"}`}>
      <HomeBroCard bro={bro} featured={featured} onOpen={editing ? () => {} : onOpen} />
      {editing && (
        <button
          type="button"
          className="home-edit-remove"
          aria-label={`Remove ${bro.name}`}
          onClick={(e) => { e.stopPropagation(); onRemove(bro.id); }}
        >
          <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
            <path d="M6 12h12"/>
          </svg>
        </button>
      )}
    </div>
  );
}

// "+ Add a bro" tile — appears at the end of Standing-by. Visible
// always; styled as a dashed ghost row in normal mode and a coral
// CTA in edit mode where adding is the explicit purpose.
function AddBroTile({ editing, onClick }) {
  return (
    <button
      type="button"
      className={`home-add-row${editing ? " home-add-row-on" : ""}`}
      onClick={onClick}
    >
      <span className="home-add-icon">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 5v14M5 12h14"/>
        </svg>
      </span>
      <span className="home-add-body">
        <span className="home-add-title">Add a bro</span>
        <span className="home-add-sub">Name them, then connect a node</span>
      </span>
      <span className="home-add-arrow">›</span>
    </button>
  );
}

// ─────────────────────────────────────────────────────────────
// Account sheet — bottom sheet that appears when the user taps the
// gear (or their avatar). Holds workspace identity, the "Manage
// bros" toggle, and a destructive Sign-out at the bottom.
// ─────────────────────────────────────────────────────────────
function HomeAccountSheet({ onClose, onEnterEdit, onAddBro, onSignOut, signOutPending }) {
  return (
    <section className="acct-sheet" role="dialog" aria-label="Account">
      <div className="acct-sheet-handle" aria-hidden="true" />

      {/* identity card */}
      <header className="acct-identity">
        <div className="acct-identity-avatar">
          <span>L</span>
        </div>
        <div className="acct-identity-body">
          <div className="acct-identity-name">Luna Park</div>
          <div className="acct-identity-mail">luna@parklane.studio</div>
        </div>
        <button type="button" className="acct-identity-edit" aria-label="Edit profile">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>
          </svg>
        </button>
      </header>

      {/* workspace section */}
      <div className="acct-section">
        <div className="acct-section-eyebrow">WORKSPACE</div>
        <button type="button" className="acct-row">
          <span className="acct-row-glyph acct-row-glyph-coral">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 9l9-6 9 6v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
            </svg>
          </span>
          <span className="acct-row-body">
            <span className="acct-row-title">Parklane Studio</span>
            <span className="acct-row-meta">4 bros · 2 connectors · admin</span>
          </span>
          <span className="acct-row-chev">›</span>
        </button>
        <button type="button" className="acct-row">
          <span className="acct-row-glyph">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>
              <circle cx="9" cy="7" r="4"/>
              <path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1A4 4 0 0 1 16 11"/>
            </svg>
          </span>
          <span className="acct-row-body">
            <span className="acct-row-title">Switch workspace</span>
            <span className="acct-row-meta">2 others available</span>
          </span>
          <span className="acct-row-chev">›</span>
        </button>
      </div>

      {/* bros section */}
      <div className="acct-section">
        <div className="acct-section-eyebrow">BROS</div>
        <button type="button" className="acct-row" onClick={onAddBro}>
          <span className="acct-row-glyph acct-row-glyph-coral">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 5v14M5 12h14"/>
            </svg>
          </span>
          <span className="acct-row-body">
            <span className="acct-row-title">Add a bro</span>
            <span className="acct-row-meta">Name them, connect a node</span>
          </span>
          <span className="acct-row-chev">›</span>
        </button>
        <button type="button" className="acct-row" onClick={onEnterEdit}>
          <span className="acct-row-glyph">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 6h13M3 12h10M3 18h7"/>
              <path d="M19 14l3 3-3 3M22 17h-5"/>
            </svg>
          </span>
          <span className="acct-row-body">
            <span className="acct-row-title">Manage bros</span>
            <span className="acct-row-meta">Rename, remove, reorder</span>
          </span>
          <span className="acct-row-chev">›</span>
        </button>
        <button type="button" className="acct-row">
          <span className="acct-row-glyph">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="4" width="18" height="16" rx="2"/>
              <path d="M3 10h18M8 4v6"/>
            </svg>
          </span>
          <span className="acct-row-body">
            <span className="acct-row-title">Connected nodes</span>
            <span className="acct-row-meta">2 online · 1 paused</span>
          </span>
          <span className="acct-row-chev">›</span>
        </button>
      </div>

      {/* app section */}
      <div className="acct-section">
        <div className="acct-section-eyebrow">APP</div>
        <button type="button" className="acct-row acct-row-compact">
          <span className="acct-row-title">Notifications</span>
          <span className="acct-row-trail">All</span>
          <span className="acct-row-chev">›</span>
        </button>
        <button type="button" className="acct-row acct-row-compact">
          <span className="acct-row-title">Voice & dictation</span>
          <span className="acct-row-trail">English (US)</span>
          <span className="acct-row-chev">›</span>
        </button>
        <button type="button" className="acct-row acct-row-compact">
          <span className="acct-row-title">Help & feedback</span>
          <span className="acct-row-chev">›</span>
        </button>
      </div>

      {/* sign out */}
      <div className="acct-foot">
        <button
          type="button"
          className={`acct-signout${signOutPending ? " acct-signout-pending" : ""}`}
          onClick={onSignOut}
        >
          {signOutPending ? (
            <React.Fragment>
              <span className="acct-signout-spin" aria-hidden="true" />
              <span>Signing out…</span>
            </React.Fragment>
          ) : (
            <React.Fragment>
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
                <path d="M16 17l5-5-5-5"/>
                <path d="M21 12H9"/>
              </svg>
              <span>Sign out of Newbro</span>
            </React.Fragment>
          )}
        </button>
        <div className="acct-version">Newbro v0.9.2 · build 27a4</div>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// Confirm-remove action sheet — iOS pattern with a danger primary
// and a cancel below in a separate card.
// ─────────────────────────────────────────────────────────────
function HomeConfirmRemove({ bro, onCancel, onConfirm }) {
  if (!bro) return null;
  const sessionWarning = bro.state === "working";
  return (
    <section className="acct-confirm" role="alertdialog" aria-label={`Remove ${bro.name}`}>
      <div className="acct-confirm-card">
        <div className="acct-confirm-head">
          <div className="acct-confirm-title">Remove {bro.name}?</div>
          <div className="acct-confirm-sub">
            {sessionWarning
              ? `${bro.name} is mid-task on ${bro.node}. The session ends, the draft is kept, and the executor disconnects.`
              : `${bro.name} disconnects from ${bro.node || "their node"} and stops appearing in your workspace. Their threads stay.`}
          </div>
        </div>
        <div className="acct-confirm-actions">
          <button type="button" className="acct-confirm-danger" onClick={() => onConfirm(bro.id)}>
            {sessionWarning ? "Stop & remove" : "Remove from workspace"}
          </button>
        </div>
      </div>
      <button type="button" className="acct-confirm-cancel" onClick={onCancel}>Cancel</button>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// HomeVariant — interactive home with account sheet, edit mode,
// and add/remove flows. Accepts initial-state props so the design
// canvas can showcase each state in its own artboard.
// ─────────────────────────────────────────────────────────────
function HomeVariant({ initialAccountOpen = false, initialEditMode = false, initialAddOpen = false, initialConfirmRemoveId = null } = {}) {
  const [bros, setBros]                   = React.useState(HOME_BROS);
  const [accountOpen, setAccountOpen]     = React.useState(initialAccountOpen);
  const [editMode, setEditMode]           = React.useState(initialEditMode);
  const [addOpen, setAddOpen]             = React.useState(initialAddOpen);
  const [confirmId, setConfirmId]         = React.useState(initialConfirmRemoveId);
  const [signOutPending, setSignOutPending] = React.useState(false);

  const working = bros.filter((b) => b.state === "working");
  const others  = bros.filter((b) => b.state !== "working");
  const confirmBro = bros.find((b) => b.id === confirmId);

  const closeAll = () => {
    setAccountOpen(false);
    setAddOpen(false);
    setConfirmId(null);
  };

  const enterEdit = () => {
    setAccountOpen(false);
    setEditMode(true);
  };
  const exitEdit = () => setEditMode(false);

  const requestRemove = (id) => setConfirmId(id);
  const confirmRemove = (id) => {
    setBros((b) => b.filter((x) => x.id !== id));
    setConfirmId(null);
  };

  const openAdd = () => {
    setAccountOpen(false);
    setAddOpen(true);
  };
  const closeAdd = () => setAddOpen(false);

  const signOut = () => {
    setSignOutPending(true);
    // visual stub — no real navigation in the prototype
    setTimeout(() => setSignOutPending(false), 1600);
  };

  const totalCount = bros.length;
  const anyOverlay = accountOpen || addOpen || confirmBro;

  return (
    <IOSDevice width={402} height={874}>
      <div className={`home${editMode ? " home-editing" : ""}${anyOverlay ? " home-dimmed" : ""}`}>
        {/* top bar — title flips when editing */}
        <header className="home-bar">
          {editMode ? (
            <React.Fragment>
              <div className="home-bar-l home-bar-l-edit">
                <div className="home-bar-titles">
                  <div className="home-bar-greet">Edit bros</div>
                  <div className="home-bar-meta">
                    Tap − to remove · drag to reorder
                  </div>
                </div>
              </div>
              <button type="button" className="home-bar-done" onClick={exitEdit}>Done</button>
            </React.Fragment>
          ) : (
            <React.Fragment>
              <button
                type="button"
                className="home-bar-l home-bar-l-tap"
                onClick={() => setAccountOpen(true)}
                aria-label="Open account"
              >
                <div className="home-bar-logo">
                  <img src="assets/newbro-logo.webp" alt="" draggable={false} />
                </div>
                <div className="home-bar-titles">
                  <div className="home-bar-greet">Hi, Luna</div>
                  <div className="home-bar-meta">
                    {working.length} of {totalCount} bros working · 2 sessions
                  </div>
                </div>
              </button>
              <button
                type="button"
                className="home-bar-btn"
                aria-label="Account"
                onClick={() => setAccountOpen(true)}
              >
                <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="3"/>
                  <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9c.2.6.7 1 1.5 1H21a2 2 0 1 1 0 4h-.1c-.7 0-1.3.4-1.5 1z"/>
                </svg>
              </button>
            </React.Fragment>
          )}
        </header>

        <main className="home-body">
          {/* In-flight (featured cards) */}
          {working.length > 0 && (
            <section className="home-section">
              <div className="home-section-head">
                <span className="home-section-eyebrow">In flight · {working.length}</span>
                <span className="home-section-sub">{editMode ? "Removing stops the task" : "Sessions currently dispatched"}</span>
              </div>
              <div className="home-flight">
                {working.map((b) => (
                  <HomeBroEditable
                    key={b.id}
                    bro={b}
                    featured
                    editing={editMode}
                    onRemove={requestRemove}
                    onOpen={() => {}}
                  />
                ))}
              </div>
            </section>
          )}

          {/* Standing by */}
          <section className="home-section">
            <div className="home-section-head">
              <span className="home-section-eyebrow">Standing by · {others.length}</span>
              {!editMode && <span className="home-section-sub">Idle, paused, or offline</span>}
            </div>
            <div className="home-list">
              {others.map((b) => (
                <HomeBroEditable
                  key={b.id}
                  bro={b}
                  editing={editMode}
                  onRemove={requestRemove}
                  onOpen={() => {}}
                />
              ))}
              {/* + Add a bro tile — always available */}
              <AddBroTile editing={editMode} onClick={() => setAddOpen(true)} />
            </div>
          </section>

          {/* Recent — hidden in edit mode so it doesn't look removable */}
          {!editMode && (
            <section className="home-section">
              <div className="home-section-head">
                <span className="home-section-eyebrow">Recent · {HOME_RECENTS.length}</span>
                <button type="button" className="home-section-link">See all</button>
              </div>
              <ul className="home-recents">
                {HOME_RECENTS.map((r) => (
                  <li key={r.id}>
                    <button type="button" className="home-recent">
                      <span className="home-recent-icon">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>
                        </svg>
                      </span>
                      <span className="home-recent-body">
                        <span className="home-recent-title">{r.title}</span>
                        <span className="home-recent-meta">{r.bro} · {r.when}</span>
                      </span>
                      <span className="home-recent-arrow">›</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </main>

        {/* overlays */}
        {(accountOpen || addOpen || confirmBro) && (
          <div className="home-scrim" onClick={closeAll} aria-hidden="true" />
        )}
        {accountOpen && (
          <HomeAccountSheet
            onClose={() => setAccountOpen(false)}
            onEnterEdit={enterEdit}
            onAddBro={openAdd}
            onSignOut={signOut}
            signOutPending={signOutPending}
          />
        )}
        {addOpen && (
          <div className="home-add-sheet-wrap">
            {window.CreateBroSheet ? <window.CreateBroSheet onClose={closeAdd} /> : null}
          </div>
        )}
        {confirmBro && (
          <HomeConfirmRemove
            bro={confirmBro}
            onCancel={() => setConfirmId(null)}
            onConfirm={confirmRemove}
          />
        )}
      </div>
    </IOSDevice>
  );
}

window.HomeVariant = HomeVariant;

// ═════════════════════════════════════════════════════════════
// 1. HALO  — voice-call vibe
// ═════════════════════════════════════════════════════════════
function HaloVariant() {
  const v = useVoice();
  if (!v) return null;
  const { mode, transcript, draft, reply, vu, script, inputMode, setInputMode, freeSubMode, setFreeSubMode, textValue, setTextValue, sendText, freeStart, stepIdx, progress, hasArtifact, audioDuration, turnKind, turnDuration, interjection } = v;
  const meta = stateMeta[mode];
  const [activeBro, setActiveBro] = React.useState("atlas");

  // Caption — what shows over the halo. In PTT we just show recording duration.
  const captionContent = (() => {
    if (mode === "listening" && inputMode === "ptt") {
      return { kind: "audio-live" };
    }
    if (mode === "listening" && inputMode === "free") {
      return { kind: "voice-live", text: transcript };
    }
    if (mode === "reporting") return { kind: "reply", text: reply };
    if (mode === "error")     return { kind: "error", text: "Studio Mac dropped — I'll resume on the same step." };
    if (mode === "thinking")  return { kind: "thinking" };
    return null;
  })();

  return (
    <IOSDevice width={402} height={874}>
      <div className={`halo halo-${meta.tone}`}>
        {/* state pill — sits below the dynamic island */}
        <div className="halo-pill">
          <span className="halo-pill-dot" />
          <span className="halo-pill-name">{M_BRO.name}</span>
          <span className="halo-pill-sep">·</span>
          <span className="halo-pill-state">{meta.label}</span>
        </div>

        {/* portrait halo */}
        <div className="halo-stage">
          <div className="halo-rings">
            <span className="halo-ring halo-ring-1" />
            <span className="halo-ring halo-ring-2" />
            <span className="halo-ring halo-ring-3" />
          </div>
          <div className="halo-portrait">
            <Mascot size={132} mode={mode} />
          </div>
          {/* tiny status under the avatar */}
          <div className="halo-substate">
            {mode === "idle"      && "I'm here when you are"}
            {mode === "listening" && (inputMode === "ptt" ? `Recording · ${formatDuration(audioDuration)}` : "I'm listening")}
            {mode === "thinking"  && "Drafting…"}
            {mode === "working"   && `${Math.round(progress)}% · ${stepIdx >= 0 ? script.steps[stepIdx]?.label : ""}`}
            {mode === "reporting" && (hasArtifact ? "1 artifact ready" : "Done")}
            {mode === "error"     && "Auto-retry in 8s"}
          </div>
        </div>

        {/* caption sheet — only shows when there's something to caption */}
        <div className="halo-caption-zone">
          {captionContent?.kind === "voice-live" && (
            <div className="halo-caption halo-caption-live">
              {captionContent.text}
              <span className="halo-caret" />
            </div>
          )}
          {captionContent?.kind === "audio-live" && (
            <div className="halo-caption halo-caption-audio">
              <span className="halo-caption-eyebrow">REC · audio · {formatDuration(audioDuration)}</span>
              <div className="halo-caption-wave">
                {Array.from({ length: 32 }).map((_, i) => {
                  const t = Math.abs(Math.sin((i + 1) * 0.4 + Date.now() * 0.005));
                  const h = 4 + t * 18 * (0.4 + vu);
                  return <i key={i} style={{ height: h }} />;
                })}
              </div>
              <span className="halo-caption-sub">Audio is sent directly — no transcript.</span>
            </div>
          )}
          {captionContent?.kind === "thinking" && (
            <div className="halo-caption halo-caption-ghost">
              <span className="halo-think-dots"><i/><i/><i/></span>
            </div>
          )}
          {captionContent?.kind === "reply" && (
            <div className="halo-caption">
              {captionContent.text}
              {mode === "reporting" && reply.length < script.reply.length && <span className="halo-caret" />}
            </div>
          )}
          {captionContent?.kind === "error" && (
            <div className="halo-caption">
              {captionContent.text}
            </div>
          )}
          {interjection && (
            <div className="halo-caption halo-caption-interject">
              <span className="halo-caption-eyebrow">Atlas · chime</span>
              {interjection}
            </div>
          )}
          {mode === "reporting" && hasArtifact && (
            <button type="button" className="halo-artifact">
              <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>
              </svg>
              <span>{script.artifact.name}</span>
              <span className="halo-artifact-arrow">›</span>
            </button>
          )}
        </div>

        {/* channel wheel — switch bros without leaving voice */}
        <MobileBroWheel
          bros={HOME_BROS}
          activeId={activeBro}
          onSelect={setActiveBro}
        />

        {/* input zone — thumb-friendly */}
        <div className="halo-foot">
          <MobileModeSwitch value={inputMode} onChange={setInputMode} />
          {inputMode !== "free" && (
            <button
              type="button"
              className={`halo-orb halo-orb-${mode}`}
              onMouseDown={() => v.hold()}
              onMouseUp={() => v.release()}
              onTouchStart={(e) => { e.preventDefault(); v.hold(); }}
              onTouchEnd={(e) => { e.preventDefault(); v.release(); }}
              aria-label="Hold to talk"
            >
              <span className="halo-orb-halo" />
              <span className="halo-orb-halo halo-orb-halo-2" />
              {mode === "listening" ? (
                <span className="halo-orb-bars">
                  {Array.from({ length: 9 }).map((_, i) => (
                    <i key={i} style={{ height: `${10 + Math.abs(Math.sin((i + 1) * 0.7 + Date.now() * 0.003)) * 28 * (0.4 + vu)}px` }} />
                  ))}
                </span>
              ) : (
                <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="9" y="3" width="6" height="12" rx="3"/>
                  <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
                </svg>
              )}
            </button>
          )}
          {inputMode !== "free" && (
            <div className="halo-typeline">
              <input
                type="text"
                className="halo-typeline-input"
                placeholder="…or type to Atlas"
                value={textValue}
                onChange={(e) => setTextValue(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && textValue.trim()) { e.preventDefault(); sendText(textValue); } }}
              />
              <button
                type="button"
                className="halo-typeline-send"
                onClick={() => sendText(textValue)}
                disabled={!textValue.trim()}
                aria-label="Send"
              >
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 19V5M5 12l7-7 7 7"/>
                </svg>
              </button>
            </div>
          )}
          {inputMode === "free" && (
            <div className="halo-free-stack">
              <FreeSubToggle value={freeSubMode} onChange={setFreeSubMode} />
              <button
                type="button"
                className={`halo-free${mode === "idle" ? " halo-free-open" : ""}`}
                onClick={() => freeStart()}
              >
                <span className={`halo-free-led halo-free-led-${freeSubMode}`} />
                <span className="halo-free-text">
                  <span className="halo-free-title">{mode === "idle" ? `Mic on · ${freeSubMode === "silent" ? "talk less" : "engage"}` : "Listening…"}</span>
                  <span className="halo-free-sub">{freeSubMode === "silent" ? "Quiet · bro replies when done" : "Active · bro engages mid-turn"}</span>
                </span>
              </button>
            </div>
          )}
        </div>
      </div>
    </IOSDevice>
  );
}

// ═════════════════════════════════════════════════════════════
// 2. THREADS — iMessage-style chat
// ═════════════════════════════════════════════════════════════
const ATLAS_THREADS = [
  { id: "sfo-jfk",   title: "SFO → JFK options", state: "working", when: "now" },
  { id: "tokyo-q1",  title: "Tokyo Q1 trip",     state: "done",    when: "Mon" },
  { id: "lh-refund", title: "Refund LH9123",     state: "open",    when: "2d" },
  { id: "sf-hotel",  title: "Hotel SF Nov",      state: "done",    when: "Wed" },
];

// ─────────────────────────────────────────────────────────────
// Codex plan mode (⇧⇥), surfaced in the thread: Atlas proposes a
// plan and waits for approval before acting. Only shown for bros
// bound to a Codex executor.
// ─────────────────────────────────────────────────────────────

// ── Plan proposal — Codex plan-mode output: a few candidate plans
//    you choose between, then approve. ───────────────────────────
function PlanProposal({ proposal, approved, onApprove, onKeep }) {
  const [sel, setSel] = React.useState(proposal.options[0].id);
  const chosen = proposal.options.find((o) => o.id === sel) || proposal.options[0];
  return (
    <div className="thr-turn thr-turn-bro">
      <div className={`plan-prop${approved ? " plan-prop-on" : ""}`}>
        <div className="plan-prop-head">
          <span className="plan-prop-glyph" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="9" width="6" height="6" rx="1.5"/>
              <rect x="15" y="4" width="6" height="6" rx="1.5"/>
              <rect x="15" y="14" width="6" height="6" rx="1.5"/>
              <path d="M9 12h3M12 7v10M12 7h3M12 17h3"/>
            </svg>
          </span>
          <span className="plan-prop-title">Proposed plans</span>
          <span className="plan-prop-tag">{proposal.options.length} OPTIONS</span>
        </div>
        <p className="plan-prop-summary">{proposal.summary}</p>
        <div className="plan-opts" role="radiogroup" aria-label="Plan options">
          {proposal.options.map((o, i) => {
            const on = o.id === sel;
            return (
              <button
                key={o.id}
                type="button"
                role="radio"
                aria-checked={on}
                className={`plan-opt${on ? " plan-opt-on" : ""}`}
                onClick={() => !approved && setSel(o.id)}
                disabled={approved && !on}
              >
                <span className="plan-opt-radio" aria-hidden="true" />
                <span className="plan-opt-body">
                  <span className="plan-opt-top">
                    <span className="plan-opt-letter">{String.fromCharCode(65 + i)}</span>
                    <span className="plan-opt-label">{o.label}</span>
                    {o.tag && <span className="plan-opt-tag">{o.tag}</span>}
                  </span>
                  <span className="plan-opt-text">{o.body}</span>
                </span>
              </button>
            );
          })}
        </div>
        {approved ? (
          <div className="plan-prop-running">
            <span className="plan-prop-running-spin" aria-hidden="true" />
            Running “{chosen.label}” — I'll report back
          </div>
        ) : (
          <div className="plan-prop-actions">
            <button type="button" className="plan-prop-approve" onClick={() => onApprove(chosen)}>
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12.5L10 18L20 6"/></svg>
              Approve &amp; run
            </button>
            <button type="button" className="plan-prop-keep" onClick={onKeep}>Keep planning</button>
          </div>
        )}
      </div>
      <div className="thr-meta">{approved ? "Plan approved · executing" : "Pick a plan · awaiting your approval"}</div>
    </div>
  );
}

function ThreadsVariant({ initialPlanMode = false, initialProposal = false } = {}) {
  const v = useVoice();
  if (!v) return null;
  const { mode, transcript, draft, reply, vu, script, inputMode, setInputMode, freeSubMode, setFreeSubMode, textValue, setTextValue, sendText, freeStart, stepIdx, progress, hasArtifact, audioDuration, turnKind, turnDuration, interjection } = v;
  const meta = stateMeta[mode];

  // Codex-only plan mode.
  const isCodex = M_BRO.executor === "Codex";
  const [planMode, setPlanMode]   = React.useState(initialPlanMode); // ⇧⇥ plan mode
  const [proposal, setProposal]   = React.useState(initialProposal);// plan-mode card shown
  const [approved, setApproved]   = React.useState(false);
  const [planTurn, setPlanTurn]   = React.useState(initialProposal ? "Find me SFO → JFK options for Nov 14–18, under $500 round-trip." : null);

  // Composer text is LOCAL to this thread instance — the voice context's
  // textValue is shared across all mounted variants, so driving the
  // composer through it would leak state between artboards.
  const [localText, setLocalText] = React.useState("");

  const handleSend = (raw) => {
    const text = (raw || "").trim();
    if (!text) return;
    // plan mode → Atlas proposes instead of acting
    if (planMode)  { setPlanTurn(text); setProposal(true); setApproved(false); setLocalText(""); return; }
    setLocalText("");
    sendText(text);
  };

  const approvePlan = () => { setApproved(true); setPlanMode(false); };

  // Active thread state — switching only updates the picker visual + header
  // subtitle for now. The voice-state context drives the conversation body.
  const [activeThreadId, setActiveThreadId] = React.useState("sfo-jfk");
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const activeThread = ATLAS_THREADS.find((t) => t.id === activeThreadId) || ATLAS_THREADS[0];

  // ── decide how to render the user's turn
  // While listening: PTT shows a live audio bubble, free shows live transcript bubble.
  // Once committed (turnKind set): render the matching bubble type.
  const showLiveAudio   = mode === "listening" && inputMode === "ptt";
  const showLiveVoice   = mode === "listening" && inputMode === "free";
  const showAudioTurn   = turnKind === "audio" && mode !== "listening";
  const showVoiceTurn   = turnKind === "voice" && mode !== "listening";
  const showTextTurn    = turnKind === "text"  && mode !== "listening";

  return (
    <IOSDevice width={402} height={874}>
      <div className="thr">
        {/* top bar */}
        <header className="thr-bar">
          <button type="button" className="thr-back" aria-label="Back">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 6l-6 6 6 6"/>
            </svg>
          </button>
          <div className="thr-bar-bro">
            <div className="thr-bar-avatar">
              <Mascot size={40} mode={mode} crop={1.0} />
            </div>
            <div className="thr-bar-meta">
              <div className="thr-bar-title-row">
                <span className="thr-bar-name">{M_BRO.name}</span>
                <span className="thr-bar-sep">·</span>
                <span className="thr-bar-thread-title">{activeThread.title}</span>
              </div>
              <div className={`thr-bar-state thr-bar-state-${meta.tone}`}>
                <span className="thr-bar-dot" />
                {meta.label} · {M_BRO.node}
              </div>
            </div>
          </div>
          <button type="button" className="thr-more" aria-label="Switch thread" onClick={() => setPickerOpen(true)}>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
              {/* stacked layers — representing the thread list */}
              <path d="M4 7l8-4 8 4-8 4z"/>
              <path d="M4 12l8 4 8-4"/>
              <path d="M4 17l8 4 8-4"/>
            </svg>
          </button>
        </header>

        {/* thread picker drawer — slides in from right when the stack icon is tapped */}
        {pickerOpen && (
          <div className="thr-drawer-backdrop" onClick={() => setPickerOpen(false)} />
        )}
        <aside className={`thr-drawer${pickerOpen ? " thr-drawer-open" : ""}`} aria-hidden={!pickerOpen}>
          <header className="thr-drawer-head">
            <div>
              <div className="thr-drawer-eyebrow">Threads with</div>
              <div className="thr-drawer-title">{M_BRO.name}</div>
            </div>
            <button type="button" className="thr-drawer-close" onClick={() => setPickerOpen(false)} aria-label="Close">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 6L6 18M6 6l12 12"/>
              </svg>
            </button>
          </header>
          <ul className="thr-drawer-list">
            {ATLAS_THREADS.map((t) => {
              const on = t.id === activeThreadId;
              const stateLabel = t.state === "working" ? "working" : t.state === "done" ? "done" : "open";
              return (
                <li key={t.id}>
                  <button
                    type="button"
                    className={`thr-drawer-item thr-drawer-item-${t.state}${on ? " thr-drawer-item-on" : ""}`}
                    onClick={() => { setActiveThreadId(t.id); setPickerOpen(false); }}
                  >
                    <span className="thr-drawer-item-dot" aria-hidden="true" />
                    <span className="thr-drawer-item-body">
                      <span className="thr-drawer-item-title">{t.title}</span>
                      <span className="thr-drawer-item-meta">
                        <span className="thr-drawer-item-state">{stateLabel}</span>
                        <span className="thr-drawer-item-sep">·</span>
                        <span className="thr-drawer-item-when">{t.when}</span>
                      </span>
                    </span>
                    {on && (
                      <span className="thr-drawer-item-check" aria-hidden="true">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M4 12.5L10 18L20 6"/>
                        </svg>
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
          <button type="button" className="thr-drawer-new">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 5v14M5 12h14"/>
            </svg>
            <span>New thread with {M_BRO.name}</span>
          </button>
        </aside>

        {/* thread */}
        <main className="thr-thread">
          {!showLiveAudio && !showLiveVoice && !showAudioTurn && !showVoiceTurn && !showTextTurn && !draft && !reply && (
            <div className="thr-day">
              <span>Just now</span>
            </div>
          )}

          {/* live or committed user turn */}
          {showLiveAudio && (
            <div className="thr-turn thr-turn-you">
              <AudioBubble duration={audioDuration} kind="you" live />
              <div className="thr-meta"><span className="thr-mic">●</span> Recording…</div>
            </div>
          )}
          {showLiveVoice && (
            <div className="thr-turn thr-turn-you">
              <div className="thr-bubble thr-bubble-you thr-bubble-live">
                {transcript}
                <span className="thr-caret thr-caret-on-coral" />
              </div>
              <div className="thr-meta">
                <span className="thr-mic">●</span> {freeSubMode === "active" ? "Free · active" : "Free · silent"} — {formatDuration(audioDuration)}
              </div>
            </div>
          )}
          {showAudioTurn && (
            <div className="thr-turn thr-turn-you">
              <AudioBubble duration={turnDuration} kind="you" />
              <div className="thr-meta">Audio · {formatDuration(turnDuration)}</div>
            </div>
          )}
          {showVoiceTurn && (
            <div className="thr-turn thr-turn-you">
              <div className="thr-bubble thr-bubble-you">{transcript}</div>
              <div className="thr-meta">Voice · {formatDuration(turnDuration)} · transcribed</div>
            </div>
          )}
          {showTextTurn && (
            <div className="thr-turn thr-turn-you">
              <div className="thr-bubble thr-bubble-you">{transcript}</div>
              <div className="thr-meta">Text · just now</div>
            </div>
          )}

          {/* bro's mid-turn interjection (free-active only) */}
          {interjection && (
            <div className="thr-turn thr-turn-bro">
              <div className="thr-bubble thr-bubble-bro thr-bubble-interject">
                {interjection}
              </div>
              <div className="thr-meta">Active · interjecting</div>
            </div>
          )}

          {/* PTT/text: brief "received" pulse since there's no draft to show */}
          {mode === "thinking" && !draft && (
            <div className="thr-turn thr-turn-bro">
              <div className="thr-bubble thr-bubble-bro thr-bubble-typing">
                <span className="thr-think-dots"><i/><i/><i/></span>
              </div>
              <div className="thr-meta">{turnKind === "audio" ? "Heard you · spinning up" : "Got it · spinning up"}</div>
            </div>
          )}

          {draft && (
            <div className="thr-turn thr-turn-bro">
              <div className={`thr-bubble thr-bubble-bro thr-bubble-mono${mode === "thinking" ? " thr-bubble-live" : ""}`}>
                {draft}
                {mode === "thinking" && <span className="thr-caret" />}
              </div>
              <div className="thr-meta">{mode === "thinking" ? "Drafting…" : "Draft"}</div>
            </div>
          )}
          {(mode === "working") && (
            <div className="thr-turn thr-turn-bro">
              <div className="thr-status">
                <div className="thr-status-head">
                  <span className="thr-status-spin" />
                  <span className="thr-status-title">{stepIdx >= 0 ? script.steps[stepIdx].label : ""}</span>
                  <span className="thr-status-pct">{Math.round(progress)}%</span>
                </div>
                <div className="thr-status-bar"><i style={{ width: `${progress}%` }} /></div>
                <div className="thr-status-foot">
                  step {stepIdx + 1} of {script.steps.length} · {script.steps[stepIdx]?.note}
                </div>
              </div>
            </div>
          )}
          {reply && (
            <div className="thr-turn thr-turn-bro">
              <div className={`thr-bubble thr-bubble-bro${mode === "reporting" && reply.length < script.reply.length ? " thr-bubble-live" : ""}`}>
                {reply}
                {mode === "reporting" && reply.length < script.reply.length && <span className="thr-caret" />}
              </div>
              {hasArtifact && (
                <button type="button" className="thr-artifact">
                  <span className="thr-artifact-icon">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>
                    </svg>
                  </span>
                  <span className="thr-artifact-body">
                    <span className="thr-artifact-name">{script.artifact.name}</span>
                    <span className="thr-artifact-meta">{script.artifact.kind} · {script.artifact.size}</span>
                  </span>
                  <span className="thr-artifact-arrow">›</span>
                </button>
              )}
              <div className="thr-meta">Just now</div>
            </div>
          )}
          {mode === "error" && (
            <div className="thr-turn thr-turn-sys">
              <div className="thr-error">
                <strong>Studio Mac dropped.</strong>
                <span>I'll resume step 2 when it reconnects. Draft is saved.</span>
              </div>
            </div>
          )}

          {/* Codex plan-mode proposal — Atlas proposes, you approve */}
          {isCodex && proposal && (
            <React.Fragment>
              {planTurn && (
                <div className="thr-turn thr-turn-you">
                  <span className="thr-plantag" aria-label="Sent in plan mode">
                    <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="3" y="9" width="6" height="6" rx="1.5"/>
                      <rect x="15" y="4" width="6" height="6" rx="1.5"/>
                      <rect x="15" y="14" width="6" height="6" rx="1.5"/>
                      <path d="M9 12h3M12 7v10M12 7h3M12 17h3"/>
                    </svg>
                    Plan mode
                  </span>
                  <div className="thr-bubble thr-bubble-you thr-bubble-plan">{planTurn}</div>
                  <div className="thr-meta">Plan request · just now</div>
                </div>
              )}
              <PlanProposal
                proposal={ATLAS_PROPOSAL}
                approved={approved}
                onApprove={approvePlan}
                onKeep={() => setProposal(true)}
              />
            </React.Fragment>
          )}
        </main>

        {/* composer */}
        <footer className="thr-composer">
          <div className="thr-toolbar">
            <MobileModeSwitch value={inputMode} onChange={setInputMode} />
            {isCodex && inputMode !== "free" && (
              <button
                type="button"
                className={`thr-planchip${planMode ? " thr-planchip-on" : ""}`}
                onClick={() => setPlanMode((o) => !o)}
                aria-pressed={planMode}
                aria-label="Plan mode"
                title="Plan mode · ⇧⇥ — Atlas proposes before acting"
              >
                <span className="thr-planchip-icon">
                  <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="9" width="6" height="6" rx="1.5"/>
                    <rect x="15" y="4" width="6" height="6" rx="1.5"/>
                    <rect x="15" y="14" width="6" height="6" rx="1.5"/>
                    <path d="M9 12h3M12 7v10M12 7h3M12 17h3"/>
                  </svg>
                </span>
                <span className="thr-planchip-label">Plan mode</span>
              </button>
            )}
          </div>
          {/* free-mode sub-toggle (only visible in free mode) */}
          {inputMode === "free" && (
            <FreeSubToggle value={freeSubMode} onChange={setFreeSubMode} />
          )}

          <div className="thr-composer-row">
            {inputMode !== "free" && (
              <>
                {mode === "listening" ? (
                  <div className="thr-ptt-rec">
                    <span className="thr-ptt-rec-dot" aria-hidden="true" />
                    <span className="thr-ptt-rec-time">{formatDuration(audioDuration)}</span>
                    <span className="thr-ptt-rec-wave" aria-hidden="true">
                      {Array.from({ length: 22 }).map((_, i) => {
                        const t = Math.abs(Math.sin((i + 1) * 0.4 + Date.now() * 0.005));
                        const h = 4 + t * 18 * (0.35 + vu);
                        return <i key={i} style={{ height: h }} />;
                      })}
                    </span>
                    <span className="thr-ptt-rec-cancel" aria-hidden="true">
                      <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M14 6l-6 6 6 6"/>
                      </svg>
                      Slide to cancel
                    </span>
                  </div>
                ) : (
                  <div className={`thr-ptt-input${planMode ? " thr-ptt-input-plan" : ""}`}>
                    <input
                      type="text"
                      className={`thr-ptt-input-field${planMode ? " thr-ptt-input-field-plan" : ""}`}
                      placeholder={
                        planMode ? "Describe the task — Atlas will plan first…"
                        : "Message Atlas — or hold the mic to talk"
                      }
                      value={localText}
                      onChange={(e) => setLocalText(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" && localText.trim()) { e.preventDefault(); handleSend(localText); } }}
                    />
                  </div>
                )}
                {(localText.trim() && mode !== "listening") ? (
                  <button
                    type="button"
                    className="thr-mic-btn thr-mic-btn-send"
                    onClick={() => handleSend(localText)}
                    aria-label="Send message"
                  >
                    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 19V5M5 12l7-7 7 7"/>
                    </svg>
                  </button>
                ) : (
                  <button
                    type="button"
                    className={`thr-mic-btn thr-mic-btn-${mode}`}
                    onMouseDown={() => v.hold()}
                    onMouseUp={() => v.release()}
                    onTouchStart={(e) => { e.preventDefault(); v.hold(); }}
                    onTouchEnd={(e) => { e.preventDefault(); v.release(); }}
                    aria-label="Hold to talk"
                  >
                    <span className="thr-mic-halo" aria-hidden="true" />
                    <span className="thr-mic-halo thr-mic-halo-2" aria-hidden="true" />
                    {mode === "listening" ? (
                      <span className="thr-mic-waves">
                        {Array.from({ length: 5 }).map((_, i) => <i key={i} style={{ animationDelay: `${i * 0.07}s` }} />)}
                      </span>
                    ) : (
                      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <rect x="9" y="3" width="6" height="12" rx="3"/>
                        <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
                      </svg>
                    )}
                  </button>
                )}
              </>
            )}
            {inputMode === "free" && (
              <button type="button" className={`thr-free${mode === "idle" ? " thr-free-open" : ""}`} onClick={() => freeStart()}>
                <span className={`thr-free-led thr-free-led-${freeSubMode}`} />
                <span className="thr-free-label">
                  {mode === "idle" ? `Always on · ${freeSubMode === "silent" ? "talk less" : "engage"} · tap to talk` : "Listening…"}
                </span>
                <span className="thr-free-waves">
                  {Array.from({ length: 16 }).map((_, i) => {
                    const t = Math.abs(Math.sin((i + 1) * 0.4 + Date.now() * 0.005));
                    const h = mode === "idle" ? 4 + t * 5 : 4 + t * 14 * (0.4 + vu);
                    return <i key={i} style={{ height: h }} />;
                  })}
                </span>
              </button>
            )}
          </div>
        </footer>
      </div>
    </IOSDevice>
  );
}

// ═════════════════════════════════════════════════════════════
// 3. CONSOLE — operator panel
// ═════════════════════════════════════════════════════════════
function ConsoleVariant() {
  const v = useVoice();
  if (!v) return null;
  const { mode, transcript, draft, reply, vu, script, inputMode, setInputMode, freeSubMode, setFreeSubMode, textValue, setTextValue, sendText, freeStart, stepIdx, progress, hasArtifact, audioDuration, turnKind, turnDuration, interjection } = v;
  const meta = stateMeta[mode];

  const showLiveAudio = mode === "listening" && inputMode === "ptt";
  const showLiveVoice = mode === "listening" && inputMode === "free";
  const showAudioTurn = turnKind === "audio" && mode !== "listening";
  const showVoiceTurn = turnKind === "voice" && mode !== "listening";
  const showTextTurn  = turnKind === "text"  && mode !== "listening";

  return (
    <IOSDevice width={402} height={874}>
      <div className="con">
        {/* compact header */}
        <header className="con-bar">
          <div className="con-bar-l">
            <span className="con-channel">CH 03</span>
            <span className="con-name">ATLAS</span>
            <span className={`con-state con-state-${meta.tone}`}>
              <span className="con-state-dot" />
              {meta.short.toUpperCase()}
            </span>
          </div>
          <div className="con-bar-r">
            <MobileModeSwitch value={inputMode} onChange={setInputMode} theme="dark" />
          </div>
        </header>
        <div className="con-subbar">
          <span className="con-subbar-node">{M_BRO.node} · session 04</span>
          <button type="button" className="con-bar-stop" aria-label="Stop">
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="6" y="6" width="12" height="12" rx="2"/>
            </svg>
            <span>Stop</span>
          </button>
        </div>

        {/* task strip */}
        {(mode === "working" || mode === "reporting" || mode === "error") && (
          <div className={`con-task con-task-${mode}`}>
            <div className="con-task-head">
              <span className="con-task-eyebrow">{mode === "reporting" ? "Done" : mode === "error" ? "Paused" : "Working"}</span>
              <span className="con-task-pct">
                {mode === "error" ? `step ${Math.max(1, stepIdx + 1)}/${script.steps.length}` : `${Math.round(progress)}%`}
              </span>
            </div>
            <div className="con-task-title">
              {mode === "reporting" ? "Compared three SFO → JFK options" :
               mode === "working" ? (stepIdx >= 0 ? script.steps[stepIdx].label : "Preparing…") :
               "Resuming on reconnect"}
            </div>
            <div className="con-task-bar"><i style={{ width: `${progress}%` }} /></div>
            <div className="con-task-steps">
              {script.steps.map((s, i) => {
                const st = mode === "reporting" ? "done"
                  : i < stepIdx ? "done"
                  : i === stepIdx ? (mode === "error" ? "pause" : "run")
                  : "queued";
                return <span key={s.label} className={`con-task-pip con-task-pip-${st}`} />;
              })}
            </div>
          </div>
        )}

        {/* transcript log */}
        <main className="con-log">
          {!showLiveAudio && !showLiveVoice && !showAudioTurn && !showVoiceTurn && !showTextTurn && !draft && !reply && (
            <div className="con-log-empty">
              <div className="con-log-empty-line">Channel is quiet.</div>
              <div className="con-log-empty-sub">
                {inputMode === "ptt"  && "Hold the mic to open a transmission."}
                {inputMode === "free" && "Open the channel to start free-talk."}
                {inputMode === "text" && "Type a message to dispatch."}
              </div>
            </div>
          )}

          {/* user's turn — varies by kind */}
          {(showLiveAudio || showAudioTurn) && (
            <div className="con-log-row con-log-row-you">
              <span className="con-log-time">14:22:08</span>
              <span className="con-log-who">YOU · AUDIO</span>
              <span className="con-log-body con-log-audio">
                <AudioBubble duration={showLiveAudio ? audioDuration : turnDuration} kind="dark" live={showLiveAudio} />
                <span className="con-log-audio-meta">
                  {showLiveAudio ? "transmitting · audio only" : "sent as audio · no transcript"}
                </span>
              </span>
            </div>
          )}
          {showLiveVoice && (
            <div className="con-log-row con-log-row-you">
              <span className="con-log-time">14:22:08</span>
              <span className="con-log-who">YOU · FREE · {freeSubMode.toUpperCase()}</span>
              <span className="con-log-body con-log-live">
                {transcript}
                <span className="con-caret" />
              </span>
            </div>
          )}
          {showVoiceTurn && (
            <div className="con-log-row con-log-row-you">
              <span className="con-log-time">14:22:08</span>
              <span className="con-log-who">YOU · VOICE</span>
              <span className="con-log-body">{transcript}</span>
            </div>
          )}
          {showTextTurn && (
            <div className="con-log-row con-log-row-you">
              <span className="con-log-time">14:22:08</span>
              <span className="con-log-who">YOU · TEXT</span>
              <span className="con-log-body">{transcript}</span>
            </div>
          )}

          {/* bro's mid-turn interjection (free-active only) */}
          {interjection && (
            <div className="con-log-row con-log-row-bro">
              <span className="con-log-time">14:22:14</span>
              <span className="con-log-who">ATLAS · CHIME</span>
              <span className="con-log-body con-log-interject">{interjection}</span>
            </div>
          )}

          {/* PTT/text: brief ack — there's no draft to render */}
          {mode === "thinking" && !draft && (
            <div className="con-log-row con-log-row-bro">
              <span className="con-log-time">14:22:14</span>
              <span className="con-log-who">ATLAS · ACK</span>
              <span className="con-log-body con-log-ack">
                <span className="con-log-spin" />
                Received · spinning up
              </span>
            </div>
          )}

          {draft && (
            <div className="con-log-row con-log-row-bro">
              <span className="con-log-time">14:22:31</span>
              <span className="con-log-who">ATLAS · DRAFT</span>
              <span className={`con-log-body con-log-mono${mode === "thinking" ? " con-log-live" : ""}`}>
                {draft}
                {mode === "thinking" && <span className="con-caret" />}
              </span>
            </div>
          )}
          {reply && (
            <div className="con-log-row con-log-row-bro">
              <span className="con-log-time">14:23:08</span>
              <span className="con-log-who">ATLAS</span>
              <span className={`con-log-body${mode === "reporting" && reply.length < script.reply.length ? " con-log-live" : ""}`}>
                {reply}
                {mode === "reporting" && reply.length < script.reply.length && <span className="con-caret" />}
              </span>
            </div>
          )}
          {hasArtifact && (
            <button type="button" className="con-attach">
              <span className="con-attach-icon">
                <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>
                </svg>
              </span>
              <span className="con-attach-name">{script.artifact.name}</span>
              <span className="con-attach-meta">{script.artifact.size}</span>
              <span className="con-attach-open">Open ›</span>
            </button>
          )}
        </main>

        {/* dense input dock */}
        <footer className="con-dock">
          {inputMode === "ptt" && (
            <button
              type="button"
              className={`con-ptt con-ptt-${mode}`}
              onMouseDown={() => v.hold()}
              onMouseUp={() => v.release()}
              onTouchStart={(e) => { e.preventDefault(); v.hold(); }}
              onTouchEnd={(e) => { e.preventDefault(); v.release(); }}
              aria-label="Push to talk"
            >
              <span className="con-ptt-light" />
              <span className="con-ptt-label">
                <span className="con-ptt-mic">
                  {mode === "listening" ? (
                    <span className="con-ptt-waves">{Array.from({ length: 6 }).map((_, i) => <i key={i} style={{ animationDelay: `${i * 0.07}s` }} />)}</span>
                  ) : (
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="9" y="3" width="6" height="12" rx="3"/>
                      <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
                    </svg>
                  )}
                </span>
                <span className="con-ptt-text">
                  <span className="con-ptt-state">
                    {mode === "listening" ? `REC · ${formatDuration(audioDuration)}` : "PUSH TO TALK"}
                  </span>
                  <span className="con-ptt-sub">{mode === "listening" ? "Audio sent directly · no transcript" : "Hold for audio transmission"}</span>
                </span>
              </span>
            </button>
          )}
          {inputMode === "free" && (
            <div className="con-free-stack">
              <FreeSubToggle value={freeSubMode} onChange={setFreeSubMode} theme="dark" />
              <button type="button" className={`con-free${mode === "idle" ? " con-free-open" : ""}`} onClick={() => freeStart()}>
                <span className={`con-free-led con-free-led-${freeSubMode}`} />
                <span className="con-free-text">
                  <span className="con-free-title">{mode === "idle" ? `OPEN · ${freeSubMode.toUpperCase()}` : "TRANSMITTING"}</span>
                  <span className="con-free-sub">{mode === "idle" ? (freeSubMode === "silent" ? "Quiet · bro replies when done" : "Active · bro engages mid-turn") : "Tap to close"}</span>
                </span>
                <span className="con-free-waves">
                  {Array.from({ length: 22 }).map((_, i) => {
                    const t = Math.abs(Math.sin((i + 1) * 0.4 + Date.now() * 0.005));
                    const h = mode === "idle" ? 4 + t * 5 : 4 + t * 14 * (0.4 + vu);
                    return <i key={i} style={{ height: h }} />;
                  })}
                </span>
              </button>
            </div>
          )}
          {inputMode === "text" && (
            <div className="con-text">
              <span className="con-text-prompt">›</span>
              <input
                type="text"
                placeholder="TYPE TO TRANSMIT"
                value={textValue}
                onChange={(e) => setTextValue(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); sendText(textValue); } }}
              />
              <button
                type="button"
                className="con-text-send"
                onClick={() => sendText(textValue)}
                disabled={!textValue.trim()}
              >
                SEND
              </button>
            </div>
          )}
        </footer>
      </div>
    </IOSDevice>
  );
}

window.HaloVariant = HaloVariant;
window.ThreadsVariant = ThreadsVariant;
window.ConsoleVariant = ConsoleVariant;
