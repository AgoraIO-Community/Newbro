/* voice-state.jsx
 * Shared voice state machine + sample script.
 *
 * MODES: idle → listening → thinking → working → reporting → error
 *
 * The simulator scripts a realistic turn:
 *   listening — user's transcript streams in token by token
 *   thinking  — bro's draft types in (mono)
 *   working   — task steps tick one by one
 *   reporting — artifact appears, bro replies
 *
 * Exposes useVoice() which returns { state, hold(), release(), setMode(), reset() }.
 * All three variants subscribe to the same instance via a React context.
 */

const VoiceCtx = React.createContext(null);
const useVoice = () => React.useContext(VoiceCtx);

// ───────────────────────────────────────────── sample script
const SCRIPT = {
  user: "Okay, I need you to compare flights from SFO to New York for next Friday. Three options under two fifty round trip, economy, and check the refund rules.",
  draft:
    "Comparing SFO ⇄ JFK for Fri 6/12 — Sun 6/14.\n" +
    "Filter: round trip · economy · ≤ $250.\n" +
    "Verify: change/refund window for each fare class.\n" +
    "Return: top 3 with carrier, depart time, fare, refund rule.",
  taskTitle: "Compare three SFO → JFK options",
  steps: [
    { label: "Pull route inventory", note: "Checked 12 carrier × time combinations." },
    { label: "Filter under $250 round trip", note: "Kept JetBlue · Delta · Frontier." },
    { label: "Verify refund rules", note: "Reading fare-class fine print." },
    { label: "Compose comparison", note: "Carrier · depart · price · refund." },
  ],
  reply:
    "Three options under $250 are ready. JetBlue 7:30 AM is the cleanest pick — $217 round trip with free changes up to 24h. Two more in the artifact. Want me to hold the first one?",
  artifact: { name: "sfo-jfk-fri.csv", size: "1.4 KB", kind: "CSV" },
};

// ───────────────────────────────────────────── token utilities
function tokenize(s) {
  // word + punctuation grouping; preserves trailing space
  const out = [];
  const re = /(\S+\s?)/g;
  let m;
  while ((m = re.exec(s)) !== null) out.push(m[1]);
  return out;
}

// ───────────────────────────────────────────── provider
function VoiceProvider({ children }) {
  const [mode, setMode] = React.useState("idle");
  // input modes:
  //   ptt  — push-to-talk: AUDIO sent directly, no transcript.
  //   free — open mic: continuous; transcribes; two sub-modes (silent / active).
  //   text — type & send.
  const [inputMode, setInputMode] = React.useState("ptt");
  // Free-mode sub-mode:
  //   silent — bro listens, drafts quietly, rarely interjects
  //   active — bro participates, may ask clarifying questions during turn
  const [freeSubMode, setFreeSubMode] = React.useState("silent");
  const [textValue, setTextValue] = React.useState("");
  const [transcript, setTranscript] = React.useState("");      // free mode only
  const [audioDuration, setAudioDuration] = React.useState(0); // ptt mode only, seconds
  // Snapshot of how the latest turn was submitted so variants render the
  // right "you said" representation even if the user flips inputMode afterwards.
  const [turnKind, setTurnKind] = React.useState(null);        // 'audio' | 'voice' | 'text'
  const [turnDuration, setTurnDuration] = React.useState(0);
  const [interjection, setInterjection] = React.useState("");  // free-active bro chime-in
  const [draft, setDraft] = React.useState("");
  const [stepIdx, setStepIdx] = React.useState(-1);
  const [progress, setProgress] = React.useState(0);
  const [reply, setReply] = React.useState("");
  const [hasArtifact, setHasArtifact] = React.useState(false);
  const [vu, setVu] = React.useState(0); // 0..1 volume meter
  const [turn, setTurn] = React.useState(0); // conversation turn counter

  const timers = React.useRef([]);
  const clearTimers = () => { timers.current.forEach(clearTimeout); timers.current = []; };
  const after = (ms, fn) => { const t = setTimeout(fn, ms); timers.current.push(t); return t; };

  // VU meter loop — animates while listening, and in free mode while idle
  // (open mic — always sampling room audio at low level)
  React.useEffect(() => {
    const live = mode === "listening" || (inputMode === "free" && mode === "idle");
    if (!live) { setVu(0); return; }
    let raf;
    const tick = () => {
      // free-mode idle stays quieter (ambient room) than active listening
      const base = mode === "listening" ? 0.45 : 0.12;
      const range = mode === "listening" ? 0.55 : 0.25;
      setVu(base + Math.random() * range);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [mode, inputMode]);

  // ── PTT (audio-only) — counts up recording duration, NO transcript
  const hold = React.useCallback(() => {
    clearTimers();
    setMode("listening");
    setTranscript("");
    setAudioDuration(0);
    setDraft("");
    setStepIdx(-1);
    setProgress(0);
    setReply("");
    setHasArtifact(false);
    setTurnKind(null);
    setInterjection("");
    // tick the duration up while held
    const start = performance.now();
    const tick = () => {
      setAudioDuration((performance.now() - start) / 1000);
      timers.current.push(setTimeout(tick, 100));
    };
    tick();
  }, []);

  // ── free mode — streams transcript token by token
  const freeListenStart = React.useCallback(() => {
    clearTimers();
    setMode("listening");
    setTranscript("");
    setAudioDuration(0);
    setDraft("");
    setStepIdx(-1);
    setProgress(0);
    setReply("");
    setHasArtifact(false);
    setTurnKind(null);
    setInterjection("");
    // count duration too
    const start = performance.now();
    const dtick = () => { setAudioDuration((performance.now() - start) / 1000); timers.current.push(setTimeout(dtick, 100)); };
    dtick();
    // stream transcript
    const toks = tokenize(SCRIPT.user);
    let i = 0;
    const step = () => {
      if (i >= toks.length) return;
      setTranscript((s) => s + toks[i]);
      // in active mode, occasionally interject mid-turn
      if (freeSubMode === "active" && i === Math.floor(toks.length * 0.55)) {
        setInterjection("Mm-hm — got the date and budget.");
        timers.current.push(setTimeout(() => setInterjection(""), 2400));
      }
      i += 1;
      after(70 + Math.random() * 80, step);
    };
    step();
  }, [freeSubMode]);

  const release = React.useCallback(() => {
    clearTimers();
    // PTT path: AUDIO sent directly — no transcript, no draft. Skip to working.
    if (inputMode === "ptt") {
      setTurnKind("audio");
      setTurnDuration(audioDuration);
      setMode("thinking");        // brief acknowledged-state with no draft
      setDraft("");
      after(400, () => {
        setMode("working");
        setStepIdx(0);
        progressRun();
      });
      return;
    }
    // Free path: commit transcript, draft phase shapes the plan from speech.
    setTurnKind("voice");
    setTurnDuration(audioDuration);
    setTranscript(SCRIPT.user);
    setMode("thinking");
    after(450, () => {
      const toks = tokenize(SCRIPT.draft);
      let i = 0;
      const tick = () => {
        if (i >= toks.length) {
          setMode("working");
          setStepIdx(0);
          progressRun();
          return;
        }
        setDraft((s) => s + toks[i]);
        i += 1;
        after(28 + Math.random() * 32, tick);
      };
      tick();
    });
  }, [inputMode, audioDuration]);

  const progressRun = () => {
    let s = 0;
    const advanceStep = () => {
      if (s >= SCRIPT.steps.length) {
        setMode("reporting");
        setHasArtifact(true);
        // type reply
        const toks = tokenize(SCRIPT.reply);
        let i = 0;
        const tick = () => {
          if (i >= toks.length) { setTurn((n) => n + 1); return; }
          setReply((r) => r + toks[i]);
          i += 1;
          after(22 + Math.random() * 26, tick);
        };
        tick();
        return;
      }
      setStepIdx(s);
      const dur = 900 + Math.random() * 500;
      const start = performance.now();
      const stepProgress = () => {
        const t = Math.min(1, (performance.now() - start) / dur);
        setProgress(((s + t) / SCRIPT.steps.length) * 100);
        if (t < 1) requestAnimationFrame(stepProgress);
        else { s += 1; after(120, advanceStep); }
      };
      requestAnimationFrame(stepProgress);
    };
    advanceStep();
  };

  const reset = React.useCallback(() => {
    clearTimers();
    setMode("idle");
    setTranscript(""); setDraft(""); setStepIdx(-1);
    setProgress(0); setReply(""); setHasArtifact(false);
    setTextValue(""); setAudioDuration(0); setTurnKind(null); setInterjection("");
  }, []);

  // ── text mode: send text directly to working (no draft phase)
  const sendText = React.useCallback((text) => {
    const body = (text ?? "").trim();
    if (!body) return;
    clearTimers();
    setMode("thinking");          // brief acknowledged-state with no draft
    setTranscript(body);
    setTurnKind("text");
    setTurnDuration(0);
    setTextValue("");
    setDraft(""); setStepIdx(-1); setProgress(0); setReply(""); setHasArtifact(false);
    setInterjection("");
    after(380, () => {
      setMode("working");
      setStepIdx(0);
      progressRun();
    });
  }, []);

  // ── free mode: tap to open the channel, simulated VAD ends the turn
  const freeStart = React.useCallback(() => {
    if (mode !== "idle") return;
    freeListenStart();
    // silent mode: shorter "silence" before sending. active: longer because bro engages.
    const endAfter = freeSubMode === "active" ? 3600 : 2600;
    after(endAfter, () => release());
  }, [mode, freeSubMode, freeListenStart, release]);

  // Force a state directly (for Tweaks panel). Fills content appropriately
  // so each mode looks "lived in" even when jumped to manually. Drafts only
  // exist in free (voice) mode — PTT/text skip straight to working.
  const force = React.useCallback((m) => {
    clearTimers();
    setMode(m);
    const kind = inputMode === "ptt" ? "audio" : inputMode === "free" ? "voice" : "text";
    const hasDraft = kind === "voice";
    if (m === "idle") {
      setTranscript(""); setDraft(""); setStepIdx(-1);
      setProgress(0); setReply(""); setHasArtifact(false);
      setAudioDuration(0); setTurnKind(null); setInterjection("");
    } else if (m === "listening") {
      if (inputMode === "ptt") { setTranscript(""); setAudioDuration(3.4); }
      else if (inputMode === "free") { setTranscript(SCRIPT.user.slice(0, 60)); setAudioDuration(2.8); }
      else { setTranscript(""); }
      setDraft(""); setStepIdx(-1); setProgress(0); setReply(""); setHasArtifact(false);
      setTurnKind(null); setInterjection("");
    } else if (m === "thinking") {
      setTurnKind(kind);
      if (kind === "audio") { setTranscript(""); setAudioDuration(8.2); setTurnDuration(8.2); }
      else { setTranscript(SCRIPT.user); setTurnDuration(8.2); }
      // draft only in free mode
      setDraft(hasDraft ? SCRIPT.draft.slice(0, 80) : "");
      setStepIdx(-1); setProgress(0); setReply(""); setHasArtifact(false);
      setInterjection("");
    } else if (m === "working") {
      setTurnKind(kind);
      if (kind === "audio") { setTranscript(""); setAudioDuration(8.2); setTurnDuration(8.2); }
      else { setTranscript(SCRIPT.user); setTurnDuration(8.2); }
      setDraft(hasDraft ? SCRIPT.draft : "");
      setStepIdx(2); setProgress(58); setReply(""); setHasArtifact(false);
      setInterjection("");
    } else if (m === "reporting") {
      setTurnKind(kind);
      if (kind === "audio") { setTranscript(""); setAudioDuration(8.2); setTurnDuration(8.2); }
      else { setTranscript(SCRIPT.user); setTurnDuration(8.2); }
      setDraft(hasDraft ? SCRIPT.draft : "");
      setStepIdx(SCRIPT.steps.length - 1);
      setProgress(100);
      setReply(SCRIPT.reply);
      setHasArtifact(true);
      setInterjection("");
    } else if (m === "error") {
      setTurnKind(kind);
      if (kind === "audio") { setTranscript(""); setAudioDuration(8.2); setTurnDuration(8.2); }
      else { setTranscript(SCRIPT.user); setTurnDuration(8.2); }
      setDraft(hasDraft ? SCRIPT.draft.slice(0, 110) : "");
      setStepIdx(1); setProgress(32);
      setReply(""); setHasArtifact(false);
      setInterjection("");
    }
  }, [inputMode]);

  // Global space-bar binding — hold to talk (PTT mode only)
  React.useEffect(() => {
    const isTyping = (e) => /input|textarea|select/i.test((e.target.tagName || "")) || e.target.isContentEditable;
    let held = false;
    const onDown = (e) => {
      if (e.code !== "Space" || e.repeat || isTyping(e)) return;
      if (inputMode !== "ptt") return;
      e.preventDefault();
      held = true;
      hold();
    };
    const onUp = (e) => {
      if (e.code !== "Space" || !held) return;
      e.preventDefault();
      held = false;
      release();
    };
    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    return () => { window.removeEventListener("keydown", onDown); window.removeEventListener("keyup", onUp); };
  }, [hold, release, inputMode]);

  const value = {
    mode, transcript, draft, stepIdx, progress, reply, hasArtifact, vu, turn,
    inputMode, setInputMode,
    freeSubMode, setFreeSubMode,
    textValue, setTextValue,
    audioDuration, turnKind, turnDuration, interjection,
    script: SCRIPT,
    hold, release, reset, force, sendText, freeStart,
  };
  return <VoiceCtx.Provider value={value}>{children}</VoiceCtx.Provider>;
}

window.VoiceProvider = VoiceProvider;
window.useVoice = useVoice;
window.VOICE_SCRIPT = SCRIPT;
