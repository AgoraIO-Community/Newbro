/* variants-channel-mobile.jsx — channel wheel exploration.
 *
 * Walkie-talkie metaphor: each bro is a channel on a horizontal dial.
 * A special "NewBro" channel auto-dispatches.
 *
 * Default: NewBro selected → router view (worker bros + 'free route' card)
 * Tune to a bro: focus view (live progress / queued reason / sleeping idle)
 * Big context-aware coral CTA at the bottom changes with state.
 *
 * Two artboards (Default / Atlas working):
 *   - ChannelDefault    — NewBro selected, router view
 *   - ChannelTuned      — Atlas selected, working view
 */

// ─── Data model ─────────────────────────────────────────────────────
const CH_CHANNELS = [
  { key: "Forge", kind: "bro", character: "rabbit", state: "idle",
    activity: "No task · resting in the workshop",
    blurb: "Rabbit's curled up on the bench. Give it something to make." },
  { key: "Scout", kind: "bro", character: "cat",    state: "idle",
    activity: "No task · watching the window",
    blurb: "Cat's perched on the sill. Send it out to scout." },
  { key: "Atlas", kind: "bro", character: "fox",    state: "working",
    activity: "Unpacking the hero visual direction",
    elapsed: "0:24", progress: 0.62,
    log: [
      { t: "01", line: "fetch screenshot · ok",            done: true  },
      { t: "02", line: "extract palette · 6 colors",        done: true  },
      { t: "03", line: "identify type pairing",             done: false },
    ] },
  { key: "NewBro", kind: "router" },
  { key: "Codex", kind: "bro", character: "person", state: "queued",
    activity: "Waits for Atlas's brief, then drafts the build.",
    waitingOn: "Atlas", queuePos: 1 },
];
const CH_ROUTER_IDX = CH_CHANNELS.findIndex((c) => c.kind === "router");
const CH_BROS = CH_CHANNELS.filter((c) => c.kind === "bro");

// ─── Channel wheel ──────────────────────────────────────────────────
// idx is the selected channel index. We compute virtual offsets and
// scale/opacity per channel based on distance from center.
const CH_ITEM_W = 96;

function ChannelWheel({ items, idx, onChange }) {
  return (
    <div className="ch-wheel">
      <div className="ch-wheel-fade ch-wheel-fade-l" aria-hidden="true" />
      <div className="ch-wheel-fade ch-wheel-fade-r" aria-hidden="true" />
      <div className="ch-wheel-track">
        <div
          className="ch-wheel-row"
          style={{ transform: `translateX(calc(50% - ${(idx + 0.5) * CH_ITEM_W}px))` }}
        >
          {items.map((c, i) => {
            const dist = Math.abs(i - idx);
            const op = Math.max(0.28, 1 - dist * 0.32);
            const sc = Math.max(0.8,  1 - dist * 0.08);
            const on = dist === 0;
            return (
              <button
                key={c.key}
                type="button"
                className={`ch-wheel-item${on ? " ch-wheel-item-on" : ""}`}
                style={{ width: CH_ITEM_W, opacity: op, transform: `scale(${sc})` }}
                onClick={() => onChange(i)}
              >
                <ChannelChip c={c} active={on} />
              </button>
            );
          })}
        </div>
      </div>
      <ChannelDial />
    </div>
  );
}

function ChannelChip({ c, active }) {
  if (c.kind === "router") {
    return (
      <div className="ch-chip ch-chip-router">
        <div className={`ch-chip-tile ch-chip-tile-router${active ? " ch-chip-tile-on" : ""}`}>
          <BroAvatar character="newbro" size={30} tone={active ? "invert" : "ink"} />
        </div>
        <span className={`ch-chip-name${active ? " ch-chip-name-on" : ""}`}>{c.key}</span>
      </div>
    );
  }
  const ringTone =
    c.state === "working" ? "live" :
    c.state === "queued"  ? "coral" :
    "ghost";
  return (
    <div className="ch-chip">
      <div className={`ch-chip-tile ch-chip-tile-ring-${ringTone}${active ? " ch-chip-tile-on" : ""}`}>
        <BroAvatar
          character={c.character}
          state={c.state}
          size={36}
        />
        {c.state === "working" && (
          <span className="ch-chip-pip ch-chip-pip-live" />
        )}
        {c.state === "queued" && (
          <span className="ch-chip-pip ch-chip-pip-queued" />
        )}
      </div>
      <span className={`ch-chip-name${active ? " ch-chip-name-on" : ""}`}>{c.key}</span>
    </div>
  );
}

// Radio-bezel dial below the wheel — major + minor ticks + center pointer.
function ChannelDial() {
  const ticks = 41;
  return (
    <div className="ch-dial">
      <svg width="100%" height="14" viewBox="-100 0 200 14" preserveAspectRatio="none">
        {Array.from({ length: ticks }).map((_, i) => {
          const off = i - (ticks - 1) / 2;
          const x = off * 5;
          const major = i % 5 === 0;
          const center = i === (ticks - 1) / 2;
          return (
            <line
              key={i}
              x1={x} y1={center ? 0 : major ? 4 : 7}
              x2={x} y2={12}
              stroke={center ? "var(--nb-coral)" : major ? "var(--nb-ink-muted)" : "var(--nb-line)"}
              strokeWidth={center ? 1.6 : 0.7}
              strokeLinecap="round"
            />
          );
        })}
      </svg>
      <svg width="14" height="9" className="ch-dial-arrow">
        <path d="M7 9 L1 0 L13 0 Z" fill="var(--nb-coral)" />
      </svg>
    </div>
  );
}

// ─── Router view (NewBro selected) ──────────────────────────────────
function RouterView() {
  const live   = CH_BROS.filter((b) => b.state === "working").length;
  const queued = CH_BROS.filter((b) => b.state === "queued").length;
  const idle   = CH_BROS.filter((b) => b.state === "idle").length;
  return (
    <div className="ch-router">
      <div className="ch-router-card">
        <div className="ch-router-card-body">
          <span className="ch-eyebrow ch-eyebrow-coral">FREE ROUTE</span>
          <h3 className="ch-router-h">Hands-free dispatch</h3>
          <p className="ch-router-sub">
            Just say what you need — NewBro picks the right bro and dispatches.
          </p>
        </div>
        <span className="ch-router-mono">FREE / ROUTE</span>
      </div>

      <div className="ch-section-head">
        <span className="ch-eyebrow">YOUR CREW</span>
        <span className="ch-section-meta">{live} live · {queued} queued · {idle} idle</span>
      </div>

      <div className="ch-roster">
        {CH_BROS.map((b) => (
          <div key={b.key} className={`ch-roster-row ch-roster-row-${b.state}`}>
            <div className="ch-roster-avatar">
              <BroAvatar character={b.character} state={b.state} size={36} />
            </div>
            <div className="ch-roster-body">
              <div className="ch-roster-row-head">
                <span className="ch-roster-name">{b.key}</span>
                {b.state === "working" && (
                  <span className="ch-tag ch-tag-live"><span className="ch-tag-dot" />live</span>
                )}
                {b.state === "queued" && (
                  <span className="ch-tag ch-tag-queued">queued</span>
                )}
                {b.state === "idle" && (
                  <span className="ch-tag ch-tag-idle">resting</span>
                )}
              </div>
              <span className="ch-roster-activity">{b.activity}</span>
            </div>
            {b.state === "working" && (
              <span className="ch-roster-mono">{b.elapsed}</span>
            )}
            {b.state === "queued" && (
              <span className="ch-roster-mono">#{b.queuePos}</span>
            )}
            {b.state === "working" && (
              <div className="ch-roster-bar">
                <span className="ch-roster-bar-fill" style={{ width: `${b.progress * 100}%` }} />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Bro focus view ────────────────────────────────────────────────
function BroFocusView({ b }) {
  return (
    <div className="ch-focus">
      <header className="ch-focus-head">
        <div className={`ch-focus-portrait ch-focus-portrait-${b.state}`}>
          <BroAvatar character={b.character} state={b.state} size={72} />
        </div>
        <div className="ch-focus-titles">
          <span className="ch-focus-eyebrow">CHANNEL · {b.character.toUpperCase()}</span>
          <h2 className="ch-focus-h">{b.key}</h2>
          <div className="ch-focus-tags">
            {b.state === "working" && (
              <span className="ch-tag ch-tag-live"><span className="ch-tag-dot" />live</span>
            )}
            {b.state === "queued" && <span className="ch-tag ch-tag-queued">queued</span>}
            {b.state === "idle"   && <span className="ch-tag ch-tag-idle">resting</span>}
            {b.elapsed && <span className="ch-tag ch-tag-mono">{b.elapsed}</span>}
          </div>
        </div>
      </header>

      {b.state === "working" && (
        <>
          <div className="ch-card">
            <div className="ch-card-head">
              <span className="ch-eyebrow">CURRENT TASK</span>
              <span className="ch-card-mono">{Math.round(b.progress * 100)}%</span>
            </div>
            <p className="ch-card-text">{b.activity}</p>
            <div className="ch-progress">
              <span className="ch-progress-fill" style={{ width: `${b.progress * 100}%` }} />
            </div>
          </div>

          <div className="ch-card ch-card-log">
            <span className="ch-eyebrow">PROGRESS</span>
            <ol className="ch-log">
              {b.log.map((row) => (
                <li key={row.t} className={`ch-log-row${row.done ? " ch-log-row-done" : " ch-log-row-running"}`}>
                  <span className="ch-log-arrow">{row.done ? "✓" : "▸"}</span>
                  <span className="ch-log-t">{row.t}</span>
                  <span className="ch-log-line">{row.line}</span>
                </li>
              ))}
            </ol>
          </div>
        </>
      )}

      {b.state === "queued" && (
        <div className="ch-card">
          <span className="ch-eyebrow">QUEUED</span>
          <p className="ch-card-text">{b.activity}</p>
          {b.waitingOn && (
            <div className="ch-wait">
              <span className="ch-wait-mono">WAIT</span>
              <span>
                holding for <strong>{b.waitingOn}</strong> to hand off
              </span>
            </div>
          )}
        </div>
      )}

      {b.state === "idle" && (
        <div className="ch-card ch-card-idle">
          <span className="ch-eyebrow">RESTING</span>
          <p className="ch-card-text ch-card-text-italic">{b.blurb}</p>
          <div className="ch-suggest">
            <span className="ch-suggest-chip">Brief a research task</span>
            <span className="ch-suggest-chip">Send it out to gather</span>
            <span className="ch-suggest-chip">+ Custom</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── CTA — context aware ──────────────────────────────────────────
function ChannelCTA({ ch }) {
  let title, sub, hint;
  if (ch.kind === "router") {
    title = "Call NewBro";
    sub   = "Hands-free · just say what you need";
    hint  = "HOLD";
  } else if (ch.state === "working") {
    title = `Listen in to ${ch.key}`;
    sub   = "Tune the channel · hear it work as it talks";
    hint  = "TUNE";
  } else if (ch.state === "queued") {
    title = `Brief ${ch.key} now`;
    sub   = "Skip the queue · hand it directly";
    hint  = "OVERRIDE";
  } else {
    title = `Wake ${ch.key}`;
    sub   = "Direct dispatch · skip NewBro";
    hint  = "OVERRIDE";
  }
  return (
    <button type="button" className="ch-cta">
      <span className="ch-cta-mic">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="3" width="6" height="12" rx="3"/>
          <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
        </svg>
      </span>
      <span className="ch-cta-body">
        <span className="ch-cta-title">{title}</span>
        <span className="ch-cta-sub">{sub}</span>
      </span>
      <span className="ch-cta-hint">{hint}</span>
    </button>
  );
}

// ─── Walkie shell ──────────────────────────────────────────────────
function WalkieShell({ startIdx }) {
  const [idx, setIdx] = React.useState(startIdx);
  const ch = CH_CHANNELS[idx];
  const isRouter = ch.kind === "router";
  return (
    <IOSDevice width={402} height={874}>
      <div className="ch-page">
        <header className="ch-bar">
          <div className="ch-bar-l">
            <div className="ch-bar-logo">
              <BroAvatar character="newbro" size={22} tone="coral" />
            </div>
            <div className="ch-bar-titles">
              <span className="ch-bar-eyebrow">WALKIE</span>
              <span className="ch-bar-name">
                {isRouter ? "NewBro" : ch.key} <span className="ch-bar-sep">·</span> {isRouter ? "router" : ch.state}
              </span>
            </div>
          </div>
          <button type="button" className="ch-bar-btn" aria-label="Settings">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3"/>
              <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9c.2.6.7 1 1.5 1H21a2 2 0 1 1 0 4h-.1c-.7 0-1.3.4-1.5 1z"/>
            </svg>
          </button>
        </header>

        <main className="ch-main">
          {isRouter ? <RouterView /> : <BroFocusView b={ch} />}
        </main>

        <div className="ch-channel-block">
          <ChannelWheel items={CH_CHANNELS} idx={idx} onChange={setIdx} />
        </div>

        <ChannelCTA ch={ch} />

        <div className="ch-type">
          <input
            type="text"
            placeholder={isRouter ? "or type a request…" : `or type to ${ch.key}…`}
          />
          <button type="button" className="ch-type-send" aria-label="Send">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 19V5M5 12l7-7 7 7"/>
            </svg>
          </button>
        </div>
      </div>
    </IOSDevice>
  );
}

function ChannelDefault() { return <WalkieShell startIdx={CH_ROUTER_IDX} />; }
function ChannelTuned()   { return <WalkieShell startIdx={CH_CHANNELS.findIndex((c) => c.key === "Atlas")} />; }
function ChannelIdle()    { return <WalkieShell startIdx={CH_CHANNELS.findIndex((c) => c.key === "Forge")} />; }

window.ChannelDefault = ChannelDefault;
window.ChannelTuned   = ChannelTuned;
window.ChannelIdle    = ChannelIdle;
