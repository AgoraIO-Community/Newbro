import { LoaderCircle, Mic, MicOff, PlayCircle, Radio, Square } from "lucide-react";
import { Button } from "../ui/button";
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
  const statusChipClass =
    voicePhase === "connected"
      ? "border-primary/15 bg-primary/10 text-primary"
      : voicePhase === "loading"
        ? "border-primary/12 bg-white/82 text-primary"
        : voicePhase === "error"
          ? "border-[#8d5a62]/12 bg-white/82 text-[#8d5a62]"
          : "border-border/70 bg-white/78 text-muted-foreground";
  const statusLabel =
    voicePhase === "connected"
      ? isMicMuted
        ? "Muted"
        : "Live"
      : voicePhase === "loading"
        ? "Starting"
        : voicePhase === "error"
          ? "Error"
          : "Ready";

  return (
    <div
      data-testid="top-voice-bar"
      className="glass-panel rounded-[28px] border border-white/80 px-4 py-4 md:px-5 md:py-4.5"
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <div className={`rounded-full border px-3 py-1.5 uppercase tracking-[0.18em] ${statusChipClass}`}>
            {statusLabel}
          </div>
          <div className="rounded-full border border-white/85 bg-white/76 px-3 py-1.5">
            {workingCount}/{bros.length} Bros Working
          </div>
          <div className="rounded-full border border-white/85 bg-white/76 px-3 py-1.5">
            {messageCount} turns
          </div>
          {blockReason ? (
            <div data-testid="voice-node-blocked-warning" className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-amber-700">
              {blockReason}
            </div>
          ) : null}
          {sessionId && voicePhase !== "idle" ? (
            <div className="rounded-full border border-white/85 bg-white/76 px-3 py-1.5">
              Session {sessionId}
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          {voicePhase === "connected" ? (
            <>
              <Button
                data-testid="voice-session-stop"
                type="button"
                variant="outline"
                size="sm"
                onClick={onStop}
                className="rounded-full bg-white/70 px-3.5 text-foreground backdrop-blur-md hover:bg-white"
              >
                <Square className="size-4 fill-current" />
                <span className="ml-1">Stop</span>
              </Button>
              <Button
                data-testid="voice-session-mic-toggle"
                type="button"
                variant="secondary"
                size="sm"
                disabled={startDisabled}
                onClick={onToggleMute}
                className="rounded-full px-3.5 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isMicMuted ? <Mic className="size-4" /> : <MicOff className="size-4" />}
                <span className="ml-1">{isMicMuted ? "Unmute" : "Mute"}</span>
              </Button>
            </>
          ) : (
            <Button
              data-testid="voice-session-start"
              type="button"
              variant="default"
              size="sm"
              disabled={startDisabled}
              onClick={onStart}
              className="rounded-full px-4 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {voicePhase === "loading" ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : voicePhase === "error" ? (
                <Radio className="size-4" />
              ) : (
                <PlayCircle className="size-4" />
              )}
              <span className="ml-1">{voicePhase === "error" ? "Retry" : "Start"}</span>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
