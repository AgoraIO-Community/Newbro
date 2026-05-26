import { LoaderCircle, Mic, MicOff, PlayCircle, Radio, Square } from "lucide-react";
import type { BroCardModel } from "./types";

export function TopVoiceBar({
  bros,
  voicePhase,
  error,
  isMicMuted,
  messageCount,
  sessionId,
  startDisabled = false,
  blockReason,
  onStart,
  onStop,
  onToggleMute,
}: {
  bros: BroCardModel[];
  voicePhase: "idle" | "loading" | "connected" | "error";
  error: string | null;
  isMicMuted: boolean;
  messageCount: number;
  sessionId: string | null;
  startDisabled?: boolean;
  blockReason?: string | null;
  onStart: () => void;
  onStop: () => void;
  onToggleMute: () => void;
}) {
  const workingCount = bros.filter((bro) => bro.status === "busy").length;
  const status =
    blockReason ? "paused" :
    voicePhase === "connected" ? "live" :
    voicePhase === "error" ? "paused" :
    "ready";
  const statusLabel =
    blockReason ? "PAUSED" :
    voicePhase === "connected" ? (isMicMuted ? "LIVE · muted" : "LIVE · listening") :
    voicePhase === "loading" ? "STARTING" :
    voicePhase === "error" ? "ERROR" :
    "READY";

  return (
    <div data-testid="top-voice-bar" className="dt-topvoice">
      <div className="dt-topvoice-pills">
        <span className={`dt-topvoice-pill dt-topvoice-pill-${status}`}>
          <span className="dt-topvoice-pill-dot" />
          {statusLabel}
        </span>
        <span className="dt-topvoice-note">{workingCount}/{bros.length} Bros working</span>
        <span className="dt-topvoice-note">{messageCount} turns</span>
        {sessionId && voicePhase !== "idle" ? <span className="dt-topvoice-note">Session {sessionId}</span> : null}
        {blockReason ? (
          <span data-testid="voice-node-blocked-warning" className="dt-topvoice-note text-[#b45309]">
            {blockReason}
          </span>
        ) : error ? (
          <span className="dt-topvoice-note text-[#b45309]">{error}</span>
        ) : null}
      </div>

      <div className="dt-topvoice-actions">
        {voicePhase === "connected" ? (
          <>
            <button data-testid="voice-session-stop" type="button" className="dt-topvoice-btn" onClick={onStop}>
              <Square className="h-3.5 w-3.5 fill-current" />
              Stop
            </button>
            <button
              data-testid="voice-session-mic-toggle"
              type="button"
              disabled={startDisabled}
              className="dt-topvoice-btn dt-topvoice-btn-primary"
              onClick={onToggleMute}
            >
              {isMicMuted ? <Mic className="h-3.5 w-3.5" /> : <MicOff className="h-3.5 w-3.5" />}
              {isMicMuted ? "Unmute" : "Mute"}
            </button>
          </>
        ) : (
          <button
            data-testid="voice-session-start"
            type="button"
            disabled={startDisabled}
            className="dt-topvoice-btn dt-topvoice-btn-primary"
            onClick={onStart}
          >
            {voicePhase === "loading" ? (
              <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
            ) : voicePhase === "error" ? (
              <Radio className="h-3.5 w-3.5" />
            ) : (
              <PlayCircle className="h-3.5 w-3.5" />
            )}
            {voicePhase === "error" ? "Retry" : "Start"}
          </button>
        )}
      </div>
    </div>
  );
}
