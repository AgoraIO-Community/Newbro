/* variant-walkie.jsx — "Walkie"
 *
 * Voice-first reimagining #2 — tactile radio-handset metaphor.
 * The bro feels like a person on the other end of a handset. A wide
 * portrait card holds visual focus; a "channel strip" on the right
 * reads like a radio scanner with timecoded transmissions. The talk
 * dock at the bottom is a physical PTT bar.
 *
 * Layout:
 *   ╭──────────────────────────────────────────────────╮
 *   │ CH 03 · ATLAS · STUDIO MAC               ●  LIVE │ ← header strip
 *   ├───────────────────────────┬──────────────────────┤
 *   │                           │ ◷ 14:22  YOU         │
 *   │     ╭──────────────╮      │   "okay i need…"     │
 *   │     │   PORTRAIT   │      │                      │
 *   │     │   (big)      │      │ ◷ 14:22  ATLAS       │
 *   │     ╰──────────────╯      │   draft (mono)       │
 *   │   ┌── VU METER ──┐        │                      │
 *   │   ▮▮▮▮▮▮▯▯▯▯▯▯▯▯         │ ◷ 14:23  ⚙ task      │
 *   │                           │                      │
 *   ├───────────────────────────┴──────────────────────┤
 *   │  ▒▒▒▒▒▒▒▒▒▒  PUSH TO TALK  ▒▒▒▒▒▒▒▒▒▒  [SPACE]   │ ← PTT bar
 *   ╰──────────────────────────────────────────────────╯
 */

const WalkieHeader = ({ mode }) => {
  const stateConf = {
    idle:      { label: "STANDBY",    tone: "calm" },
    listening: { label: "RX · YOU",   tone: "live" },
    thinking:  { label: "DRAFTING",   tone: "warm" },
    working:   { label: "EXECUTING",  tone: "info" },
    reporting: { label: "TX · ATLAS", tone: "live" },
    error:     { label: "NO CARRIER", tone: "warn" },
  }[mode];
  return (
    <div className="wk-header">
      <div className="wk-header-l">
        <span className="wk-channel">CH 03</span>
        <span className="wk-sep">/</span>
        <span className="wk-bro-name">ATLAS</span>
        <span className="wk-sep">/</span>
        <span className="wk-node">Studio Mac</span>
      </div>
      <div className={`wk-header-r wk-tone-${stateConf.tone}`}>
        <span className="wk-state-dot" />
        <span className="wk-state-label">{stateConf.label}</span>
      </div>
    </div>
  );
};

// Use the actual Newbro mascot logo rather than a procedural face.
// The tinted ring around it shifts with the mode; the image itself stays
// constant so the bro is always recognizable.
const WalkiePortrait = ({ mode }) => {
  const live = mode === "listening" || mode === "thinking" || mode === "working" || mode === "reporting";
  const tone = mode === "error" ? "warn" : live ? "active" : "calm";
  return (
    <div className={`wk-portrait wk-portrait-${tone}`}>
      <div className="wk-portrait-paper">
        <img src="assets/newbro-logo.webp" alt="Atlas" className="wk-portrait-img" draggable={false} />
        {live && <span className="wk-portrait-ring" />}
      </div>
      {mode === "thinking" && (
        <div className="wk-thought">
          <i /><i /><i />
        </div>
      )}
    </div>
  );
};

const WalkieVu = ({ mode, vu, progress }) => {
  // 18 vertical bars; behavior changes by mode
  const bars = Array.from({ length: 18 });
  return (
    <div className={`wk-vu wk-vu-${mode}`}>
      <div className="wk-vu-label-row">
        <span className="wk-vu-label">{mode === "working" ? "PROGRESS" : "AUDIO IN"}</span>
        <span className="wk-vu-meter">
          {mode === "working" ? `${Math.round(progress)}%` :
           mode === "listening" ? `${Math.round(vu * 100)}%` :
           mode === "idle" ? "—" : "0%"}
        </span>
      </div>
      <div className="wk-vu-bars">
        {bars.map((_, i) => {
          let active = false;
          if (mode === "listening") {
            const t = Math.abs(Math.sin((i + 1) * 0.45 + Date.now() * 0.005));
            active = t * (0.5 + vu) > (i / bars.length) * 0.85;
          } else if (mode === "working") {
            active = (i / bars.length) * 100 < progress;
          } else if (mode === "reporting") {
            active = i < bars.length - 1;
          } else if (mode === "thinking") {
            const t = (Date.now() / 300 + i * 0.6) % bars.length;
            active = Math.abs(t - i) < 2;
          }
          return <i key={i} className={active ? "wk-vu-on" : ""} />;
        })}
      </div>
      <div className="wk-vu-marks">
        <span>-60</span><span>-40</span><span>-20</span><span>0</span>
      </div>
    </div>
  );
};

const ChannelLine = ({ time, who, body, mono, live, kind }) => (
  <div className={`wk-line wk-line-${who.toLowerCase()}${live ? " wk-line-live" : ""}${kind ? " wk-line-" + kind : ""}`}>
    <div className="wk-line-meta">
      <span className="wk-line-time">{time}</span>
      <span className="wk-line-who">{who}</span>
      {live && <span className="wk-line-livedot" />}
    </div>
    <div className={`wk-line-body${mono ? " wk-mono" : ""}`}>
      {body}
      {live && <span className="wk-caret" />}
    </div>
  </div>
);

const WalkieChannel = ({ mode, transcript, draft, stepIdx, progress, reply, script, hasArtifact }) => {
  const lines = [];
  if (mode !== "idle") lines.push({ key: "open", time: "14:22:04", who: "SYS", body: "Session opened · CH 03", kind: "sys" });
  if (transcript) lines.push({
    key: "you", time: "14:22:08", who: "YOU", body: transcript,
    live: mode === "listening",
  });
  if (draft) lines.push({
    key: "draft", time: "14:22:31", who: "ATLAS", body: draft, mono: true,
    live: mode === "thinking",
  });
  if (mode === "working" || mode === "reporting" || mode === "error") {
    const stepLine = stepIdx >= 0 ? script.steps[Math.min(stepIdx, script.steps.length - 1)] : null;
    lines.push({
      key: "exec", time: "14:22:55", who: "SYS",
      body: mode === "working"
        ? `EXEC · step ${stepIdx + 1}/${script.steps.length} · ${stepLine?.label}`
        : mode === "reporting"
        ? `EXEC · complete · ${script.steps.length} steps · 1 artifact`
        : `EXEC · paused · executor lost`,
      kind: mode === "error" ? "warn" : "sys",
    });
  }
  if (reply) lines.push({
    key: "reply", time: "14:23:08", who: "ATLAS", body: reply,
    live: mode === "reporting" && reply.length < script.reply.length,
  });
  if (hasArtifact) lines.push({
    key: "art", time: "14:23:08", who: "SYS",
    body: `ATTACHED · ${script.artifact.name} · ${script.artifact.size}`,
    kind: "ok",
  });

  return (
    <div className="wk-channel">
      <div className="wk-channel-head">
        <span className="wk-eyebrow">Live channel</span>
        <span className="wk-channel-count">{lines.length} transmissions</span>
      </div>
      <div className="wk-channel-body">
        {lines.length === 0 ? (
          <div className="wk-channel-empty">
            <div>Channel quiet.</div>
            <div className="wk-channel-empty-sub">Hold the PTT bar to open a transmission.</div>
          </div>
        ) : (
          lines.map((l) => (
            <ChannelLine key={l.key} time={l.time} who={l.who} body={l.body} mono={l.mono} live={l.live} kind={l.kind} />
          ))
        )}
      </div>
    </div>
  );
};

const WalkieModeSwitch = ({ value, onChange }) => (
  <div className="wk-mode-switch" role="tablist" aria-label="Input mode">
    {[
      { v: "ptt",  label: "PTT" },
      { v: "free", label: "Open" },
      { v: "text", label: "Text" },
    ].map((opt) => (
      <button
        key={opt.v}
        type="button"
        role="tab"
        aria-selected={value === opt.v}
        className={`wk-mode-switch-btn${value === opt.v ? " wk-mode-switch-btn-on" : ""}`}
        onClick={() => onChange(opt.v)}
      >
        {opt.label}
      </button>
    ))}
  </div>
);

const WalkieTextBar = ({ value, onChange, onSend, mode }) => {
  const disabled = mode === "thinking" || mode === "working";
  return (
    <div className={`wk-text-bar${disabled ? " wk-text-bar-disabled" : ""}`}>
      <span className="wk-text-bar-prompt">›</span>
      <input
        type="text"
        className="wk-text-bar-field"
        placeholder={disabled ? "ATLAS BUSY · TYPE TO INTERRUPT" : "TYPE TO TRANSMIT"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); } }}
        disabled={disabled}
      />
      <span className="wk-text-bar-counter">{value.length}/280</span>
      <button
        type="button"
        className="wk-text-bar-send"
        onClick={onSend}
        disabled={!value.trim() || disabled}
      >
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12h14M13 6l6 6-6 6"/>
        </svg>
        <span>Send</span>
      </button>
    </div>
  );
};

const WalkieFreeBar = ({ mode, vu, onTap }) => {
  const isAmbient = mode === "idle";
  const bars = Array.from({ length: 36 });
  return (
    <div className={`wk-free-bar${isAmbient ? " wk-free-bar-ambient" : ""}`}>
      <button
        type="button"
        className="wk-free-bar-btn"
        onClick={onTap}
        aria-label={isAmbient ? "Open free channel" : "Close channel"}
      >
        <span className="wk-free-bar-led" />
        <span className="wk-free-bar-status">
          <span className="wk-free-bar-title">
            {isAmbient ? "CHANNEL OPEN" :
             mode === "listening" ? "TRANSMITTING" :
             mode === "thinking" ? "DRAFTING" :
             mode === "working" ? "EXECUTING" :
             mode === "reporting" ? "RECEIVING" : "PAUSED"}
          </span>
          <span className="wk-free-bar-sub">
            {isAmbient ? "Always-on — just talk" :
             "Tap to close"}
          </span>
        </span>
        <span className="wk-free-bar-waves">
          {bars.map((_, i) => {
            const t = Math.abs(Math.sin((i + 1) * 0.32 + Date.now() * 0.005));
            const h = mode === "idle"
              ? 4 + t * 4 * (0.5 + vu * 2)
              : 4 + t * 14 * (0.4 + vu);
            return <i key={i} style={{ height: h }} />;
          })}
        </span>
      </button>
    </div>
  );
};

const WalkiePTT = ({ mode, onMouseDown, onMouseUp, onMouseLeave }) => {
  const isLive = mode === "listening";
  const label = {
    idle: "Push to talk",
    listening: "Release to send",
    thinking: "Hold to interrupt",
    working: "Hold to interrupt",
    reporting: "Hold for follow-up",
    error: "Channel paused",
  }[mode];
  return (
    <div className="wk-ptt-wrap">
      <button
        type="button"
        className={`wk-ptt wk-ptt-${mode}`}
        onMouseDown={onMouseDown}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseLeave}
        disabled={mode === "error"}
        aria-label="Push to talk"
      >
        <span className="wk-ptt-glow" />
        <span className="wk-ptt-grid">
          {Array.from({ length: 22 }).map((_, i) => <i key={i} />)}
        </span>
        <span className="wk-ptt-content">
          <span className="wk-ptt-mic">
            {isLive ? (
              <span className="wk-ptt-waves">
                {Array.from({ length: 7 }).map((_, i) => <i key={i} style={{ animationDelay: `${i * 0.07}s` }} />)}
              </span>
            ) : (
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="9" y="3" width="6" height="12" rx="3"/>
                <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
              </svg>
            )}
          </span>
          <span className="wk-ptt-label">{label}</span>
          <span className="wk-ptt-kbd"><kbd>SPACE</kbd></span>
        </span>
      </button>
    </div>
  );
};

function WalkieVariant() {
  const v = useVoice();
  if (!v) return null;
  const { mode, transcript, draft, stepIdx, progress, reply, hasArtifact, vu, script, inputMode, setInputMode, textValue, setTextValue, sendText, freeStart } = v;
  return (
    <div className="wk-page">
      <WalkieHeader mode={mode} />
      <div className="wk-body">
        <section className="wk-portrait-col">
          <WalkiePortrait mode={mode} />
          <div className="wk-portrait-meta">
            <div className="wk-portrait-name">Atlas</div>
            <div className="wk-portrait-role">Travel researcher</div>
          </div>
          <WalkieVu mode={mode} vu={vu} progress={progress} />
        </section>
        <section className="wk-channel-col">
          <WalkieChannel
            mode={mode}
            transcript={transcript}
            draft={draft}
            stepIdx={stepIdx}
            progress={progress}
            reply={reply}
            script={script}
            hasArtifact={hasArtifact}
          />
        </section>
      </div>
      <div className="wk-input-row">
        <WalkieModeSwitch value={inputMode} onChange={setInputMode} />
        <div className="wk-input-zone">
          {inputMode === "ptt" && (
            <WalkiePTT
              mode={mode}
              onMouseDown={() => v.hold()}
              onMouseUp={() => v.release()}
              onMouseLeave={() => mode === "listening" && v.release()}
            />
          )}
          {inputMode === "text" && (
            <WalkieTextBar
              value={textValue}
              onChange={setTextValue}
              onSend={() => sendText(textValue)}
              mode={mode}
            />
          )}
          {inputMode === "free" && (
            <WalkieFreeBar mode={mode} vu={vu} onTap={() => freeStart()} />
          )}
        </div>
      </div>
    </div>
  );
}

window.WalkieVariant = WalkieVariant;
