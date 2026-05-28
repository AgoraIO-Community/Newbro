/* app.jsx — host: DesignCanvas with three voice variants, Tweaks panel.
 *
 * The Tweaks panel can:
 *   - Force voice state across all three variants in lockstep
 *   - Reset / replay the simulation
 *
 * Holding SPACE anywhere also runs the full simulation
 *   (hold → listening, release → thinking → working → reporting).
 */

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "mode": "auto",
  "inputMode": "ptt",
  "freeSubMode": "silent",
  "showHints": true
}/*EDITMODE-END*/;

const MODE_LABELS = {
  auto: "Auto",
  idle: "Idle",
  listening: "Listening",
  thinking: "Thinking",
  working: "Working",
  reporting: "Done",
  error: "Error",
};

// Sync voice state with the tweak panel: when mode is anything other than
// "auto", force the voice state into that mode. When it's "auto", leave the
// simulator alone (so hold-space drives the flow normally).
function TweakSync({ mode, inputMode, freeSubMode }) {
  const v = useVoice();
  React.useEffect(() => {
    if (!v) return;
    // expose a global handle for verification/testing
    window.__voice = v;
  }, [v]);
  React.useEffect(() => {
    if (!v) return;
    if (mode === "auto") return;
    v.force(mode);
  }, [mode, v]);
  React.useEffect(() => {
    if (!v) return;
    v.setInputMode(inputMode);
  }, [inputMode, v]);
  React.useEffect(() => {
    if (!v) return;
    v.setFreeSubMode(freeSubMode);
  }, [freeSubMode, v]);
  return null;
}

// A small helper banner that floats inside each artboard, showing what to do.
// Suppressed in idle so the design reads clean by default.
function HoldHint({ active, inputMode }) {
  if (!active) return null;
  const label = inputMode === "free"
    ? "Tap the open-channel button"
    : "Hold space anywhere, or type";
  return (
    <div style={{
      position: "absolute", top: 8, left: 8,
      padding: "5px 9px",
      background: "rgba(255,255,255,0.92)",
      backdropFilter: "blur(8px)",
      border: "1px solid rgba(255,106,61,0.2)",
      borderRadius: 999,
      fontSize: 10,
      letterSpacing: "0.14em",
      textTransform: "uppercase",
      color: "#ff6a3d",
      fontWeight: 600,
      pointerEvents: "none",
      zIndex: 5,
      display: "flex",
      alignItems: "center",
      gap: 6,
    }}>
      <span style={{
        width: 5, height: 5, borderRadius: "50%",
        background: "#ff6a3d",
        animation: "stg-pulse 1.6s ease-in-out infinite",
      }} />
      {label}
    </div>
  );
}

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);

  return (
    <VoiceProvider>
      <TweakSync mode={t.mode} inputMode={t.inputMode} freeSubMode={t.freeSubMode} />
      <DesignCanvas>
        <DCSection
          id="voice-desktop"
          title="Voice interaction — desktop"
          subtitle="The live workbench. Bro grid on home, active session on detail. Sidebar + glass top bar + right rail."
        >
          <DCArtboard id="dt-home" label="Home — workspace (4 bros)" width={1440} height={900}>
            <div style={{ position: "relative", width: "100%", height: "100%", background: "transparent" }}>
              <HomeDesktop />
            </div>
          </DCArtboard>
          <DCArtboard id="dt-thread" label="Bro detail — active session" width={1440} height={900}>
            <div style={{ position: "relative", width: "100%", height: "100%", background: "transparent" }}>
              <BroDetailActiveDesktop />
            </div>
          </DCArtboard>
        </DCSection>

        <DCSection
          id="onboarding-desktop"
          title="First-run & offline states — desktop"
          subtitle="The same flow on the workbench shell: invitation gate, empty workspace, create-and-connect modal, and the bro detail page when the node drops."
        >
          <DCArtboard id="dt-signin" label="Sign in — email + invitation code" width={1440} height={900}>
            <div style={{ position: "relative", width: "100%", height: "100%", background: "transparent" }}>
              <SignInDesktop />
            </div>
          </DCArtboard>
          <DCArtboard id="dt-empty-home" label="Empty workspace — no bros yet" width={1440} height={900}>
            <div style={{ position: "relative", width: "100%", height: "100%", background: "transparent" }}>
              <FirstRunHomeDesktop />
            </div>
          </DCArtboard>
          <DCArtboard id="dt-create-bro" label="Create & connect a bro" width={1440} height={900}>
            <div style={{ position: "relative", width: "100%", height: "100%", background: "transparent" }}>
              <CreateBroDesktop />
            </div>
          </DCArtboard>
          <DCArtboard id="dt-bro-offline" label="Bro detail — node offline (send blocked)" width={1440} height={900}>
            <div style={{ position: "relative", width: "100%", height: "100%", background: "transparent" }}>
              <BroDetailOfflineDesktop />
            </div>
          </DCArtboard>
        </DCSection>

        <DCSection
          id="onboarding"
          title="First-run & offline states"
          subtitle="Sign in with an invitation, set up your first bro and connector, and what happens when the executor node drops."
        >
          <DCArtboard id="signin" label="Sign in — email + invitation code" width={440} height={920}>
            <div style={{ position: "relative", width: "100%", height: "100%", display: "grid", placeItems: "center", background: "transparent" }}>
              <SignInVariant />
            </div>
          </DCArtboard>
          <DCArtboard id="empty-home" label="Empty workspace — no bros yet" width={440} height={920}>
            <div style={{ position: "relative", width: "100%", height: "100%", display: "grid", placeItems: "center", background: "transparent" }}>
              <FirstRunHomeVariant />
            </div>
          </DCArtboard>
          <DCArtboard id="create-bro" label="Create & connect a bro" width={440} height={920}>
            <div style={{ position: "relative", width: "100%", height: "100%", display: "grid", placeItems: "center", background: "transparent" }}>
              <CreateBroVariant />
            </div>
          </DCArtboard>
          <DCArtboard id="bro-offline" label="Bro detail — node offline (send blocked)" width={440} height={920}>
            <div style={{ position: "relative", width: "100%", height: "100%", display: "grid", placeItems: "center", background: "transparent" }}>
              <ThreadsOfflineVariant />
            </div>
          </DCArtboard>
        </DCSection>

        <DCSection
          id="mobile"
          title="Voice interaction — mobile"
          subtitle="Use Tweaks to flip input mode (PTT / Free / Text) and force any voice state."
        >
          <DCArtboard id="home" label="Home — workspace" width={440} height={920}>
            <div style={{ position: "relative", width: "100%", height: "100%", display: "grid", placeItems: "center", background: "transparent" }}>
              <HomeVariant />
            </div>
          </DCArtboard>
          <DCArtboard id="home-account" label="Home — account sheet (sign out)" width={440} height={920}>
            <div style={{ position: "relative", width: "100%", height: "100%", display: "grid", placeItems: "center", background: "transparent" }}>
              <HomeVariant initialAccountOpen />
            </div>
          </DCArtboard>
          <DCArtboard id="home-edit" label="Home — manage bros (add / remove)" width={440} height={920}>
            <div style={{ position: "relative", width: "100%", height: "100%", display: "grid", placeItems: "center", background: "transparent" }}>
              <HomeVariant initialEditMode />
            </div>
          </DCArtboard>
          <DCArtboard id="home-confirm-remove" label="Home — confirm remove a bro" width={440} height={920}>
            <div style={{ position: "relative", width: "100%", height: "100%", display: "grid", placeItems: "center", background: "transparent" }}>
              <HomeVariant initialEditMode initialConfirmRemoveId="forge" />
            </div>
          </DCArtboard>
          <DCArtboard id="threads" label="Threads — chat thread" width={440} height={920}>
            <div style={{ position: "relative", width: "100%", height: "100%", display: "grid", placeItems: "center", background: "transparent" }}>
              <ThreadsVariant />
            </div>
          </DCArtboard>
        </DCSection>
      </DesignCanvas>

      <TweaksPanel>
        <TweakSection label="Input mode" />
        <TweakRadio
          label="Send a message via"
          value={t.inputMode === "text" ? "ptt" : t.inputMode}
          options={[
            { value: "ptt",  label: "Tap to send" },
            { value: "free", label: "Always on" },
          ]}
          onChange={(v) => setTweak("inputMode", v)}
        />
        <div style={{ fontSize: 10.5, color: "rgba(41,38,27,0.6)", lineHeight: 1.5, padding: "2px 0" }}>
          <span style={{ fontWeight: 600 }}>Tap to send</span> — hold to talk, or type alongside · <span style={{ fontWeight: 600 }}>Always on</span> — voice only, hands-free
        </div>
        {t.inputMode === "free" && (
          <TweakRadio
            label="Free sub-mode"
            value={t.freeSubMode}
            options={[
              { value: "silent", label: "Silent" },
              { value: "active", label: "Active" },
            ]}
            onChange={(v) => setTweak("freeSubMode", v)}
          />
        )}
        <TweakSection label="Voice state" />
        <TweakSelect
          label="Mode"
          value={t.mode}
          options={[
            { value: "auto", label: "Auto — drive via input" },
            { value: "idle", label: "Idle / standby" },
            { value: "listening", label: "Listening" },
            { value: "thinking", label: "Thinking · drafting" },
            { value: "working", label: "Working · executing" },
            { value: "reporting", label: "Reporting back · done" },
            { value: "error", label: "Error · executor offline" },
          ]}
          onChange={(v) => setTweak("mode", v)}
        />
        <div style={{ fontSize: 10.5, color: "rgba(41,38,27,0.6)", lineHeight: 1.5, padding: "2px 0" }}>
          In <span style={{ fontWeight: 600 }}>Auto</span> + PTT, hold <kbd style={{
            padding: "1px 5px", border: "1px solid rgba(0,0,0,0.15)", borderRadius: 4,
            background: "rgba(255,255,255,0.6)", fontFamily: "JetBrains Mono, monospace",
            fontSize: 10, letterSpacing: 0,
          }}>Space</kbd> to run the full turn.
        </div>
      </TweaksPanel>
    </VoiceProvider>
  );
}

ReactDOM.createRoot(document.getElementById("app")).render(<App />);
