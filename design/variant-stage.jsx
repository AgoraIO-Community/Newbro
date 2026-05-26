/* variant-stage.jsx — "Stage"
 *
 * Voice-first reimagining #1.
 * The page is a paper stage. A single centered talk orb dominates.
 * Above it, the conversation unfolds as turns (you ▸ bro). Draft,
 * tasks, and status fold into edges so they're glanceable but never
 * the focus.
 *
 * Layout:
 *   ╭──────────────────────────────────────────────────╮
 *   │  ◐ Newbro · Atlas · standby             [tasks ▾]│
 *   │                                                  │
 *   │   you ▸ "...transcript..."                       │
 *   │                                                  │
 *   │   atlas ▸ draft (mono)                           │
 *   │                                                  │
 *   │             ▓▓▓▓▓▓▓▓▓▓                           │
 *   │             ▓  ORB  ▓                            │
 *   │             ▓▓▓▓▓▓▓▓▓▓                           │
 *   │      press & hold [space] or click               │
 *   ╰──────────────────────────────────────────────────╯
 */

const StageBro = ({ name, mode }) => {
  // Status label per mode
  const label = {
    idle: "Standby · Studio Mac",
    listening: "Listening",
    thinking: "Thinking",
    working: "Working",
    reporting: "Reporting back",
    error: "Executor lost — Studio Mac offline",
  }[mode];

  const tone = {
    idle: "calm", listening: "live", thinking: "warm",
    working: "info", reporting: "live", error: "warn",
  }[mode];

  return (
    <div className="stg-bro">
      <div className={`stg-orbette stg-orbette-${tone}`}>
        <span className="stg-orbette-pulse" />
        <svg viewBox="0 0 28 28" width="22" height="22" fill="none">
          <circle cx="14" cy="14" r="12" stroke="currentColor" strokeWidth="1.7"/>
          <path d="M9 12.5 Q14 9 19 12.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/>
          <circle cx="11.5" cy="14.5" r="1" fill="currentColor"/>
          <circle cx="16.5" cy="14.5" r="1" fill="currentColor"/>
          <path d="M11 17.5 Q14 19 17 17.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      </div>
      <div className="stg-bro-text">
        <div className="stg-bro-name">{name}</div>
        <div className={`stg-bro-state stg-bro-state-${tone}`}>
          <span className="stg-bro-dot" />
          {label}
        </div>
      </div>
    </div>
  );
};

const StageTaskPill = ({ mode, step, total, progress }) => {
  if (mode === "idle" || mode === "listening" || mode === "thinking") {
    return (
      <div className="stg-pill stg-pill-quiet">
        <span className="stg-pill-eyebrow">Tasks</span>
        <span className="stg-pill-text">No work in flight</span>
      </div>
    );
  }
  if (mode === "working") {
    return (
      <div className="stg-pill stg-pill-info">
        <span className="stg-pill-eyebrow">Working</span>
        <span className="stg-pill-text">{step?.label}</span>
        <span className="stg-pill-meta">{Math.round(progress)}% · step {Math.min(total, (step ? 1 : 0))}/{total}</span>
        <span className="stg-pill-bar"><i style={{ width: `${progress}%` }} /></span>
      </div>
    );
  }
  if (mode === "reporting") {
    return (
      <div className="stg-pill stg-pill-live">
        <span className="stg-pill-eyebrow">Done</span>
        <span className="stg-pill-text">{total} steps · 1 artifact</span>
      </div>
    );
  }
  return (
    <div className="stg-pill stg-pill-warn">
      <span className="stg-pill-eyebrow">Paused</span>
      <span className="stg-pill-text">Reconnect to resume</span>
    </div>
  );
};

const StageInputSwitch = ({ value, onChange }) => (
  <div className="stg-input-switch" role="tablist" aria-label="Input mode">
    {[
      { v: "ptt",  label: "Push to talk", hint: "hold" },
      { v: "free", label: "Free talk",    hint: "open mic" },
      { v: "text", label: "Text",         hint: "type" },
    ].map((opt) => (
      <button
        key={opt.v}
        type="button"
        role="tab"
        aria-selected={value === opt.v}
        className={`stg-input-switch-btn${value === opt.v ? " stg-input-switch-btn-on" : ""}`}
        onClick={() => onChange(opt.v)}
      >
        <span className="stg-input-switch-label">{opt.label}</span>
        <span className="stg-input-switch-hint">{opt.hint}</span>
      </button>
    ))}
  </div>
);

const StageTextInput = ({ value, onChange, onSend, mode }) => {
  const disabled = mode === "working" || mode === "thinking";
  return (
    <div className={`stg-text-input${disabled ? " stg-text-input-disabled" : ""}`}>
      <span className="stg-text-input-icon">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 12h16M14 6l6 6-6 6"/>
        </svg>
      </span>
      <input
        type="text"
        className="stg-text-input-field"
        placeholder={
          mode === "thinking" ? "Atlas is drafting…" :
          mode === "working"  ? "Atlas is working — message to interrupt" :
                                "Tell Atlas what to build…"
        }
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); } }}
        disabled={disabled}
      />
      <button
        type="button"
        className="stg-text-input-send"
        onClick={onSend}
        disabled={!value.trim() || disabled}
        aria-label="Send"
      >
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12h14M13 6l6 6-6 6"/>
        </svg>
      </button>
    </div>
  );
};

const StageFreeIndicator = ({ mode, vu, onTap }) => {
  const bars = Array.from({ length: 12 }, (_, i) => i);
  const isAmbient = mode === "idle";
  return (
    <div className={`stg-free${isAmbient ? " stg-free-ambient" : " stg-free-active"}`}>
      <button
        type="button"
        className="stg-free-orb"
        onClick={onTap}
        aria-label={isAmbient ? "Start free-talk" : "Channel open"}
      >
        <span className="stg-free-pulse" />
        <span className="stg-free-pulse stg-free-pulse-2" />
        <span className="stg-free-bars">
          {bars.map((i) => (
            <i
              key={i}
              style={{
                height: `${4 + Math.abs(Math.sin((i + 1) * 0.65 + Date.now() * 0.004)) * 22 * (0.3 + vu)}px`,
              }}
            />
          ))}
        </span>
      </button>
      <div className="stg-free-meta">
        <div className="stg-free-label">
          {isAmbient ? "Channel open · ambient" :
           mode === "listening" ? "Atlas heard the start of a turn" :
           mode === "thinking" ? "Atlas is composing" :
           mode === "working" ? "Working — interrupt anytime" :
           mode === "reporting" ? "Channel still open" : "Channel paused"}
        </div>
        <div className="stg-free-sub">
          {isAmbient ? "Just talk. I'll pick up where you pause." : "Tap to close the channel"}
        </div>
      </div>
    </div>
  );
};

const StageOrb = ({ mode, vu, onMouseDown, onMouseUp, onMouseLeave }) => {
  // Orb visual responds to mode
  const ringClass = `stg-orb stg-orb-${mode}`;
  // Pre-render a fixed set of mic bars so layout doesn't reflow each frame
  const bars = Array.from({ length: 9 }, (_, i) => i);
  return (
    <div className="stg-orb-wrap">
      <button
        className={ringClass}
        onMouseDown={onMouseDown}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseLeave}
        type="button"
        aria-label="Hold to talk"
      >
        <span className="stg-orb-halo" />
        <span className="stg-orb-halo stg-orb-halo-2" />
        <span className="stg-orb-core">
          {mode === "listening" ? (
            <span className="stg-orb-bars">
              {bars.map((i) => (
                <i
                  key={i}
                  style={{
                    height: `${10 + Math.abs(Math.sin((i + 1) * 0.7 + Date.now() * 0.003)) * 30 * (0.4 + vu)}px`,
                    animationDelay: `${i * 0.07}s`,
                  }}
                />
              ))}
            </span>
          ) : mode === "thinking" ? (
            <span className="stg-orb-think">
              <i /><i /><i />
            </span>
          ) : mode === "working" ? (
            <span className="stg-orb-cog">
              <svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1l2.1-2.1M17 7l2.1-2.1"/>
              </svg>
            </span>
          ) : mode === "reporting" ? (
            <span className="stg-orb-check">
              <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 12.5 L10 18 L20 6"/>
              </svg>
            </span>
          ) : mode === "error" ? (
            <span className="stg-orb-error">
              <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 8v5M12 17v.5"/>
                <circle cx="12" cy="12" r="10"/>
              </svg>
            </span>
          ) : (
            <span className="stg-orb-mic">
              <svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <rect x="9" y="3" width="6" height="12" rx="3"/>
                <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
              </svg>
            </span>
          )}
        </span>
      </button>
      <div className="stg-orb-hint">
        {mode === "idle" && <><span>Press &amp; hold</span><kbd>Space</kbd><span>or click</span></>}
        {mode === "listening" && <><span className="stg-orb-hint-live">I'm listening</span></>}
        {mode === "thinking" && <span className="stg-orb-hint-soft">One second — shaping the draft</span>}
        {mode === "working" && <span className="stg-orb-hint-soft">Atlas has it. Talk again to interrupt.</span>}
        {mode === "reporting" && <span className="stg-orb-hint-soft">Tap to take it from here</span>}
        {mode === "error" && <span className="stg-orb-hint-warn">Studio Mac dropped offline · auto-retry in 8s</span>}
      </div>
    </div>
  );
};

const StageTurn = ({ who, body, mode, time, isLive }) => (
  <div className={`stg-turn stg-turn-${who}${isLive ? " stg-turn-live" : ""}`}>
    <div className="stg-turn-head">
      <span className="stg-turn-who">{who === "you" ? "You" : "Atlas"}</span>
      <span className="stg-turn-time">{time}</span>
      {isLive && <span className="stg-turn-livedot" />}
    </div>
    <div className={`stg-turn-body ${who === "atlas" ? "stg-turn-mono" : ""}`}>
      {body}
      {isLive && <span className="stg-caret" />}
    </div>
  </div>
);

function StageVariant() {
  const v = useVoice();
  if (!v) return null;
  const { mode, transcript, draft, stepIdx, progress, reply, hasArtifact, vu, script, inputMode, setInputMode, textValue, setTextValue, sendText, freeStart } = v;

  // Build conversation turns from current state
  const showYouTurn = transcript.length > 0;
  const showDraftTurn = draft.length > 0;
  const showReplyTurn = reply.length > 0 || hasArtifact;

  const currentStep = stepIdx >= 0 ? script.steps[stepIdx] : null;

  return (
    <div className="stg-page">
      {/* top eyebrow + bro + tasks-pill */}
      <header className="stg-header">
        <StageBro name="Atlas" mode={mode} />
        <StageTaskPill
          mode={mode}
          step={currentStep}
          total={script.steps.length}
          progress={progress}
        />
      </header>

      {/* conversation column — flows up from center */}
      <main className="stg-flow">
        {!showYouTurn && !showDraftTurn && !showReplyTurn && (
          <div className="stg-flow-empty">
            <div className="stg-flow-empty-line">
              {inputMode === "ptt"  && "Hold the orb and tell Atlas what to build."}
              {inputMode === "text" && "Type a message — Atlas will draft it."}
              {inputMode === "free" && "Open the channel and just talk."}
            </div>
            <div className="stg-flow-empty-sub">
              He'll shape a draft, then dispatch when you confirm.
            </div>
          </div>
        )}
        {showYouTurn && (
          <StageTurn
            who="you"
            body={transcript}
            time={mode === "listening" ? "now" : "just now"}
            isLive={mode === "listening"}
          />
        )}
        {showDraftTurn && (
          <StageTurn
            who="atlas"
            body={draft}
            time={mode === "thinking" ? "drafting…" : "draft"}
            isLive={mode === "thinking"}
          />
        )}
        {/* working state — inline step ticker, not a turn */}
        {mode === "working" && (
          <div className="stg-steps">
            <div className="stg-steps-head">
              <span className="stg-steps-eyebrow">Atlas is working</span>
              <span className="stg-steps-meta">{Math.round(progress)}%</span>
            </div>
            <ul className="stg-steps-list">
              {script.steps.map((s, i) => {
                const cls = i < stepIdx ? "done" : i === stepIdx ? "run" : "queued";
                return (
                  <li key={s.label} className={`stg-step stg-step-${cls}`}>
                    <span className="stg-step-mark">
                      {cls === "done" ? "✓" : cls === "run" ? <span className="stg-step-spin" /> : "·"}
                    </span>
                    <span className="stg-step-label">{s.label}</span>
                    {cls === "run" && <span className="stg-step-note">{s.note}</span>}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        {showReplyTurn && (
          <StageTurn
            who="atlas"
            body={reply}
            time={hasArtifact ? "now · 1 artifact" : "now"}
            isLive={mode === "reporting" && reply.length < script.reply.length}
          />
        )}
        {mode === "reporting" && hasArtifact && (
          <div className="stg-artifact">
            <div className="stg-artifact-icon">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>
              </svg>
            </div>
            <div className="stg-artifact-body">
              <div className="stg-artifact-name">{script.artifact.name}</div>
              <div className="stg-artifact-meta">{script.artifact.kind} · {script.artifact.size}</div>
            </div>
            <button type="button" className="stg-artifact-open">Open</button>
          </div>
        )}
        {mode === "error" && (
          <div className="stg-error">
            <div className="stg-error-row">
              <span className="stg-error-icon">!</span>
              <div>
                <div className="stg-error-title">Studio Mac dropped mid-step.</div>
                <div className="stg-error-sub">I'll resume on the same step when it's back. Draft is saved.</div>
              </div>
            </div>
            <div className="stg-error-actions">
              <button type="button" className="stg-btn">Pick a new node</button>
              <button type="button" className="stg-btn stg-btn-quiet">Wait it out</button>
            </div>
          </div>
        )}
      </main>

      {/* input zone — switches by mode */}
      <footer className="stg-foot">
        <StageInputSwitch value={inputMode} onChange={setInputMode} />
        {inputMode === "ptt" && (
          <StageOrb
            mode={mode}
            vu={vu}
            onMouseDown={() => v.hold()}
            onMouseUp={() => v.release()}
            onMouseLeave={() => mode === "listening" && v.release()}
          />
        )}
        {inputMode === "text" && (
          <StageTextInput
            value={textValue}
            onChange={setTextValue}
            onSend={() => sendText(textValue)}
            mode={mode}
          />
        )}
        {inputMode === "free" && (
          <StageFreeIndicator
            mode={mode}
            vu={vu}
            onTap={() => freeStart()}
          />
        )}
      </footer>
    </div>
  );
}

window.StageVariant = StageVariant;
