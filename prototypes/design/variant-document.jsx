/* variant-document.jsx — "Document"
 *
 * Voice-first reimagining #3.
 * The draft IS the page. The whole surface is a sheet of paper that
 * Atlas is writing on while you talk. Ghost text (what you said, in
 * coral italics) appears first, then "crystallizes" into the draft
 * lines below. When work runs, task notes appear as margin annotations.
 * A thin "tape" at the bottom is the only voice chrome.
 *
 * Layout:
 *   ╭───────────────────────────────────────────────╮
 *   │ Atlas · standby                       6/10/26 │ ← top bar
 *   │                                               │
 *   │   Comparing SFO ⇄ JFK for Fri 6/12...        │
 *   │   Filter: round trip · economy · ≤ $250.     │   draft
 *   │   ┊                                           │   (mono, growing)
 *   │   ┊ "okay i need you to compare..."  ←ghost   │
 *   │                                               │
 *   │              ┌─ margin ─┐                     │
 *   │              │ ✓ pulled │                     │
 *   │              │ ⌗ filter │                     │
 *   │              └──────────┘                     │
 *   ├───────────────────────────────────────────────┤
 *   │  ◐ ▮▮▮▮▮▮▮▮▮▮▮▮  hold space to dictate        │ ← tape
 *   ╰───────────────────────────────────────────────╯
 */

const DocHeader = ({ mode }) => {
  const stateInfo = {
    idle:      { label: "standby" },
    listening: { label: "transcribing" },
    thinking:  { label: "drafting" },
    working:   { label: "executing" },
    reporting: { label: "ready" },
    error:     { label: "paused" },
  }[mode];
  return (
    <header className="doc-header">
      <div className="doc-header-l">
        <div className="doc-mark">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 4h12l4 4v12H4z"/>
            <path d="M16 4v4h4M8 12h8M8 16h6"/>
          </svg>
        </div>
        <div>
          <div className="doc-header-name">draft · sfo-jfk-fri</div>
          <div className="doc-header-sub">
            <span>Atlas</span>
            <span className="doc-sep">·</span>
            <span className="doc-header-state">{stateInfo.label}</span>
          </div>
        </div>
      </div>
      <div className="doc-header-r">
        <div className="doc-rev">rev 03 · auto-saved</div>
        <div className="doc-date">Sat · Jun 10</div>
      </div>
    </header>
  );
};

// Annotations live in the right margin. Shape:
//   { kind: 'step'|'note'|'art'|'err', state: 'done'|'run'|'queued', text }
const DocMargin = ({ mode, stepIdx, progress, hasArtifact, script }) => {
  if (mode === "idle") return <aside className="doc-margin doc-margin-empty"><div className="doc-margin-empty-text">No annotations yet</div></aside>;
  const notes = [];
  if (mode === "listening") {
    notes.push({ kind: "note", text: "I'll commit this as I hear it." });
  }
  if (mode === "thinking") {
    notes.push({ kind: "note", text: "Shaping a plan from your transcript." });
  }
  if (mode === "working" || mode === "reporting") {
    script.steps.forEach((s, i) => {
      const state = i < stepIdx ? "done" : i === stepIdx ? "run" : "queued";
      const displayState = mode === "reporting" ? "done" : state;
      notes.push({ kind: "step", state: displayState, text: s.label, note: i === stepIdx && mode === "working" ? s.note : null });
    });
    if (mode === "working") {
      notes.push({ kind: "prog", text: `${Math.round(progress)}% complete` });
    }
  }
  if (hasArtifact) {
    notes.push({ kind: "art", text: script.artifact.name, sub: `${script.artifact.kind} · ${script.artifact.size}` });
  }
  if (mode === "error") {
    notes.push({ kind: "err", text: "Studio Mac dropped offline.", sub: "Resuming on step 2 when it returns." });
  }

  return (
    <aside className="doc-margin">
      <div className="doc-margin-eyebrow">In-flight</div>
      <ul className="doc-margin-list">
        {notes.map((n, i) => (
          <li key={i} className={`doc-mn doc-mn-${n.kind}${n.state ? " doc-mn-" + n.state : ""}`}>
            <span className="doc-mn-mark">
              {n.kind === "step" && (n.state === "done" ? "✓" : n.state === "run" ? <span className="doc-mn-spin" /> : "·")}
              {n.kind === "note" && "›"}
              {n.kind === "prog" && "%"}
              {n.kind === "art" && (
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>
                </svg>
              )}
              {n.kind === "err" && "!"}
            </span>
            <div className="doc-mn-body">
              <span className="doc-mn-text">{n.text}</span>
              {n.note && <span className="doc-mn-note">{n.note}</span>}
              {n.sub && <span className="doc-mn-sub">{n.sub}</span>}
            </div>
          </li>
        ))}
      </ul>
    </aside>
  );
};

const DocSheet = ({ mode, transcript, draft, reply, hasArtifact, script }) => {
  // Decide whether to show ghost (live transcript) inline above the draft
  const showGhost = transcript && (mode === "listening" || mode === "thinking");
  const showDraft = draft.length > 0;
  const showReply = reply.length > 0;

  return (
    <div className="doc-sheet">
      {/* Line numbers gutter */}
      <div className="doc-gutter">
        {Array.from({ length: 18 }).map((_, i) => (
          <span key={i} className={i < (draft.split("\n").length) ? "doc-gutter-live" : ""}>{String(i + 1).padStart(2, "0")}</span>
        ))}
      </div>

      <div className="doc-body">
        {/* Intent block — what you said, shown above the plan */}
        {showGhost && (
          <div className="doc-intent">
            <div className="doc-intent-eyebrow">Intent · transcribed from you</div>
            <div className={`doc-intent-text${mode === "listening" ? " doc-intent-live" : ""}`}>
              "{transcript}{mode === "listening" && <span className="doc-caret-coral" />}"
            </div>
          </div>
        )}

        {/* Empty paper hint */}
        {!showGhost && !showDraft && (
          <div className="doc-empty">
            <div className="doc-empty-mark">
              <span className="doc-caret-coral" />
            </div>
            <div className="doc-empty-line">Atlas is waiting at the page.</div>
            <div className="doc-empty-sub">Hold <kbd>Space</kbd> and tell him what to draft. Words appear here as you speak.</div>
          </div>
        )}

        {/* The draft */}
        {showDraft && (
          <div className="doc-draft">
            <div className="doc-draft-eyebrow">Plan</div>
            <div className="doc-draft-text">
              {draft.split("\n").map((line, i) => (
                <div key={i} className="doc-draft-line">
                  {line || "\u00A0"}
                  {mode === "thinking" && i === draft.split("\n").length - 1 && <span className="doc-caret-coral" />}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Reply block when reporting */}
        {showReply && (
          <div className="doc-reply">
            <div className="doc-reply-eyebrow">Atlas wrote back</div>
            <div className="doc-reply-text">
              {reply}
              {mode === "reporting" && reply.length < script.reply.length && <span className="doc-caret" />}
            </div>
            {hasArtifact && (
              <div className="doc-attach">
                <span className="doc-attach-icon">
                  <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>
                  </svg>
                </span>
                <span className="doc-attach-name">{script.artifact.name}</span>
                <span className="doc-attach-meta">{script.artifact.size}</span>
                <button type="button" className="doc-attach-open">Open</button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

const DocModeTabs = ({ value, onChange }) => (
  <div className="doc-mode-tabs" role="tablist" aria-label="Input mode">
    {[
      { v: "ptt", label: "Push to talk" },
      { v: "free", label: "Free talk" },
      { v: "text", label: "Text" },
    ].map((opt) => (
      <button
        key={opt.v}
        type="button"
        role="tab"
        aria-selected={value === opt.v}
        className={`doc-mode-tab${value === opt.v ? " doc-mode-tab-on" : ""}`}
        onClick={() => onChange(opt.v)}
      >
        {opt.label}
      </button>
    ))}
  </div>
);

const DocTextTape = ({ value, onChange, onSend, mode }) => {
  const disabled = mode === "thinking" || mode === "working";
  return (
    <div className={`doc-tape doc-tape-text${disabled ? " doc-tape-text-disabled" : ""}`}>
      <span className="doc-tape-prompt">›</span>
      <input
        type="text"
        className="doc-tape-text-field"
        placeholder={disabled ? "Atlas is busy — type to interrupt" : "Type a message to Atlas…"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); } }}
        disabled={disabled}
      />
      <span className="doc-tape-text-counter">{value.length ? `${value.length} chars` : "⏎ to send"}</span>
      <button
        type="button"
        className="doc-tape-text-send"
        onClick={onSend}
        disabled={!value.trim() || disabled}
        aria-label="Send"
      >
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12h14M13 6l6 6-6 6"/>
        </svg>
      </button>
    </div>
  );
};

const DocFreeTape = ({ mode, vu, onTap }) => {
  const isAmbient = mode === "idle";
  const samples = Array.from({ length: 56 });
  return (
    <div className={`doc-tape doc-tape-free${isAmbient ? " doc-tape-free-ambient" : ""}`}>
      <button type="button" className="doc-tape-free-led" onClick={onTap} aria-label={isAmbient ? "Close" : "Close channel"}>
        <span className="doc-tape-free-led-dot" />
      </button>
      <div className="doc-tape-text">
        <div className="doc-tape-state">
          {isAmbient ? "open mic · listening for a turn" :
           mode === "listening" ? "transmitting…" :
           mode === "thinking" ? "transcribing" :
           mode === "working" ? "atlas is working — interrupt anytime" :
           mode === "reporting" ? "done · channel still open" : "paused"}
        </div>
        <div className="doc-tape-strip">
          {samples.map((_, i) => {
            let h;
            if (mode === "listening") {
              const t = Math.abs(Math.sin((i + 1) * 0.4 + Date.now() * 0.006));
              h = 4 + t * 14 * (0.4 + vu);
            } else if (isAmbient) {
              const t = Math.abs(Math.sin((i + 1) * 0.6 + Date.now() * 0.003));
              h = 3 + t * 4 * (0.4 + vu * 1.5);
            } else if (mode === "thinking") {
              const c = (Date.now() / 24) % samples.length;
              h = 3 + Math.max(0, 10 - Math.abs(c - i)) * 1.3;
            } else if (mode === "working") {
              h = 3 + Math.sin(i * 0.6) * 1.5 + 4;
            } else if (mode === "reporting") {
              h = 3 + (i % 4) * 1.5;
            } else {
              h = 2 + (i % 3 === 0 ? 2 : 0);
            }
            return <i key={i} style={{ height: h }} />;
          })}
        </div>
      </div>
      <div className="doc-tape-time">
        <span className="doc-tape-counter">{isAmbient ? "LIVE" : "REC"}</span>
        <span className="doc-tape-free-close">Close</span>
      </div>
    </div>
  );
};

const DocTape = ({ mode, vu, onMouseDown, onMouseUp, onMouseLeave }) => {
  // The "tape" is a slim recording strip — a level meter + a small mic chip
  const stateText = {
    idle: "ready · hold space",
    listening: "recording",
    thinking: "transcribing",
    working: "atlas is working — interrupt anytime",
    reporting: "done · hold space for follow-up",
    error: "paused · waiting for executor",
  }[mode];

  const isLive = mode === "listening";
  // 40 vertical sample bars
  const samples = Array.from({ length: 56 });
  return (
    <div className={`doc-tape doc-tape-${mode}`}>
      <button
        type="button"
        className={`doc-tape-mic doc-tape-mic-${mode}`}
        onMouseDown={onMouseDown}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseLeave}
        aria-label="Hold to talk"
      >
        {isLive ? (
          <span className="doc-tape-rec">REC</span>
        ) : mode === "thinking" || mode === "working" ? (
          <span className="doc-tape-spin" />
        ) : mode === "reporting" ? (
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 12.5 L10 18 L20 6"/>
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="3" width="6" height="12" rx="3"/>
            <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
          </svg>
        )}
      </button>
      <div className="doc-tape-text">
        <div className="doc-tape-state">{stateText}</div>
        <div className="doc-tape-strip">
          {samples.map((_, i) => {
            // height per mode
            let h;
            if (mode === "listening") {
              const t = Math.abs(Math.sin((i + 1) * 0.4 + Date.now() * 0.006));
              h = 4 + t * 14 * (0.4 + vu);
            } else if (mode === "thinking") {
              // travelling pulse
              const c = (Date.now() / 24) % samples.length;
              h = 3 + Math.max(0, 10 - Math.abs(c - i)) * 1.3;
            } else if (mode === "working") {
              h = 3 + Math.sin(i * 0.6) * 1.5 + 4;
            } else if (mode === "reporting") {
              h = 3 + (i % 4) * 1.5;
            } else {
              h = 2 + (i % 3 === 0 ? 2 : 0);
            }
            return <i key={i} style={{ height: h }} />;
          })}
        </div>
      </div>
      <div className="doc-tape-time">
        <span className="doc-tape-counter">
          {mode === "idle" ? "00:00" :
           mode === "listening" ? "00:08" :
           mode === "thinking" ? "00:09" :
           mode === "working" ? "00:24" :
           mode === "reporting" ? "00:47" : "—:—"}
        </span>
        <kbd>Space</kbd>
      </div>
    </div>
  );
};

function DocumentVariant() {
  const v = useVoice();
  if (!v) return null;
  const { mode, transcript, draft, stepIdx, progress, reply, hasArtifact, vu, script, inputMode, setInputMode, textValue, setTextValue, sendText, freeStart } = v;
  return (
    <div className="doc-page">
      <DocHeader mode={mode} />
      <div className="doc-canvas">
        <DocSheet
          mode={mode}
          transcript={transcript}
          draft={draft}
          reply={reply}
          hasArtifact={hasArtifact}
          script={script}
        />
        <DocMargin
          mode={mode}
          stepIdx={stepIdx}
          progress={progress}
          hasArtifact={hasArtifact}
          script={script}
        />
      </div>
      <div className="doc-input-row">
        <DocModeTabs value={inputMode} onChange={setInputMode} />
        {inputMode === "ptt" && (
          <DocTape
            mode={mode}
            vu={vu}
            onMouseDown={() => v.hold()}
            onMouseUp={() => v.release()}
            onMouseLeave={() => mode === "listening" && v.release()}
          />
        )}
        {inputMode === "text" && (
          <DocTextTape
            value={textValue}
            onChange={setTextValue}
            onSend={() => sendText(textValue)}
            mode={mode}
          />
        )}
        {inputMode === "free" && (
          <DocFreeTape mode={mode} vu={vu} onTap={() => freeStart()} />
        )}
      </div>
    </div>
  );
}

window.DocumentVariant = DocumentVariant;
