import { startTransition, useEffect, useEffectEvent, useRef, useState } from "react";
import {
  activateConnectorSession,
  getConnectorConfig,
  prepareConnectorSession,
  stopConnectorSessionBeacon,
  type ConnectorActivateResponse,
} from "../../lib/connector-client";
import {
  loadAgoraBrowserStack,
  teardownVoiceSession,
  type ActiveVoiceResources,
  type VoiceTranscriptTurn,
} from "../../lib/voice-runtime";

export type VoiceSessionPhase = "idle" | "loading" | "connected" | "error";

export type VoiceSessionState = {
  phase: VoiceSessionPhase;
  error: string | null;
  activeSession: ConnectorActivateResponse | null;
  transcriptSession: ConnectorActivateResponse | null;
  transcript: VoiceTranscriptTurn[];
  lastTranscriptUpdateAt: string | null;
  lastToolkitMessage: string | null;
  isMicMuted: boolean;
  agentState: string;
};

const INITIAL_VOICE_SESSION_STATE: VoiceSessionState = {
  phase: "idle",
  error: null,
  activeSession: null,
  transcriptSession: null,
  transcript: [],
  lastTranscriptUpdateAt: null,
  lastToolkitMessage: null,
  isMicMuted: false,
  agentState: "idle",
};

export function useVoiceSession() {
  const [state, setState] = useState<VoiceSessionState>(INITIAL_VOICE_SESSION_STATE);
  const resourcesRef = useRef<ActiveVoiceResources | null>(null);
  const mountedRef = useRef(false);
  const generationRef = useRef(0);
  const stateRef = useRef(state);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const applyState = useEffectEvent((updater: (current: VoiceSessionState) => VoiceSessionState) => {
    if (!mountedRef.current) {
      return;
    }
    setState(updater);
  });

  const start = useEffectEvent(async (synapseSessionId: string | null) => {
    if (stateRef.current.phase === "loading" || stateRef.current.phase === "connected") {
      return;
    }
    if (!synapseSessionId) {
      const message = "Newbro session is still connecting. Try voice mode again in a moment.";
      applyState((current) => ({
        ...current,
        phase: "error",
        error: message,
        activeSession: null,
        isMicMuted: false,
        lastToolkitMessage: message,
      }));
      return;
    }

    const generation = ++generationRef.current;
    applyState((current) => ({
      ...current,
      phase: "loading",
      error: null,
      activeSession: null,
      transcriptSession: null,
      transcript: [],
      lastTranscriptUpdateAt: null,
      lastToolkitMessage: "Preparing voice session.",
      isMicMuted: false,
      agentState: "idle",
    }));

    let rtcClient: any | null = null;
    let micTrack: any | null = null;
    let rtmClient: any | null = null;
    let voiceAi: any | null = null;

    try {
      const loadedConfig = await getConnectorConfig();
      if (!loadedConfig.ready) {
        throw new Error(
          loadedConfig.missing_requirements.length > 0
            ? `Voice connector is missing: ${loadedConfig.missing_requirements.join(", ")}`
            : "Voice connector is not ready.",
        );
      }

      const prepared = await prepareConnectorSession({
        synapse_session_id: synapseSessionId,
      });
      const { AgoraRTC, AgoraRTM, AgoraVoiceAI, AgoraVoiceAIEvents, TranscriptHelperMode } =
        await loadAgoraBrowserStack();

      if (!mountedRef.current || generationRef.current !== generation) {
        return;
      }

      rtcClient = AgoraRTC.createClient({ mode: "rtc", codec: "vp8" });
      rtcClient.on("user-published", async (user: any, mediaType: string) => {
        await rtcClient.subscribe(user, mediaType);
        if (mediaType === "audio") {
          user.audioTrack?.play();
        }
      });
      rtcClient.on("user-unpublished", (user: any, mediaType: string) => {
        if (mediaType === "audio") {
          user.audioTrack?.stop();
        }
      });

      rtmClient = new AgoraRTM.RTM(prepared.app_id, prepared.user_rtm_uid);
      await rtmClient.login({ token: prepared.token });
      await rtmClient.subscribe(prepared.channel_name, { withMessage: true });

      voiceAi = await AgoraVoiceAI.init({
        rtcEngine: rtcClient,
        rtmConfig: { rtmEngine: rtmClient },
        renderMode: TranscriptHelperMode.AUTO,
      });

      voiceAi.on(AgoraVoiceAIEvents.TRANSCRIPT_UPDATED, (nextTranscript: VoiceTranscriptTurn[]) => {
        if (!mountedRef.current || generationRef.current !== generation) {
          return;
        }
        startTransition(() => {
          setState((current) => ({
            ...current,
            transcript: nextTranscript,
            lastTranscriptUpdateAt: new Date().toISOString(),
          }));
        });
      });
      voiceAi.on(AgoraVoiceAIEvents.AGENT_STATE_CHANGED, (_agentUserId: string, next: any) => {
        if (!mountedRef.current || generationRef.current !== generation) {
          return;
        }
        setState((current) => ({
          ...current,
          agentState: next?.state ?? "idle",
        }));
      });
      voiceAi.on(AgoraVoiceAIEvents.AGENT_ERROR, (_agentUserId: string, next: any) => {
        if (!mountedRef.current || generationRef.current !== generation) {
          return;
        }
        const message = next?.message ?? "Voice agent pipeline error.";
        setState((current) => ({
          ...current,
          error: message,
          lastToolkitMessage: message,
        }));
      });
      voiceAi.on(AgoraVoiceAIEvents.MESSAGE_ERROR, (_agentUserId: string, next: any) => {
        if (!mountedRef.current || generationRef.current !== generation) {
          return;
        }
        const message = next?.message ?? "Voice agent message delivery failed.";
        setState((current) => ({
          ...current,
          error: message,
          lastToolkitMessage: message,
        }));
      });
      voiceAi.on(AgoraVoiceAIEvents.AGENT_INTERRUPTED, () => {
        if (!mountedRef.current || generationRef.current !== generation) {
          return;
        }
        setState((current) => ({
          ...current,
          lastToolkitMessage: "Agent speech interrupted.",
        }));
      });
      voiceAi.on(AgoraVoiceAIEvents.DEBUG_LOG, (message: string) => {
        if (!mountedRef.current || generationRef.current !== generation) {
          return;
        }
        setState((current) => ({
          ...current,
          lastToolkitMessage: message,
        }));
      });

      await rtcClient.join(prepared.app_id, prepared.channel_name, prepared.token, prepared.uid);
      micTrack = await AgoraRTC.createMicrophoneAudioTrack();
      await rtcClient.publish([micTrack]);
      voiceAi.subscribeMessage(prepared.channel_name);

      const activated = await activateConnectorSession({
        prepared_session_id: prepared.prepared_session_id,
      });

      if (!mountedRef.current || generationRef.current !== generation) {
        await teardownVoiceSession(
          {
            bindingId: activated.binding_id,
            rtcClient,
            micTrack,
            rtmClient,
            voiceAi,
          },
          true,
        );
        return;
      }

      resourcesRef.current = {
        bindingId: activated.binding_id,
        rtcClient,
        micTrack,
        rtmClient,
        voiceAi,
      };

      setState((current) => ({
        ...current,
        phase: "connected",
        error: null,
        activeSession: activated,
        transcriptSession: activated,
        isMicMuted: false,
        lastToolkitMessage: current.lastToolkitMessage ?? "Voice toolkit subscribed.",
      }));
    } catch (error) {
      await teardownVoiceSession(
        {
          bindingId: "",
          rtcClient,
          micTrack,
          rtmClient,
          voiceAi,
        },
        false,
      );

      if (!mountedRef.current || generationRef.current !== generation) {
        return;
      }

      const message =
        error instanceof Error ? error.message : "Failed to start the voice session.";
      setState((current) => ({
        ...current,
        phase: "error",
        error: message,
        activeSession: null,
        isMicMuted: false,
        lastToolkitMessage: message,
      }));
    }
  });

  const stop = useEffectEvent(async () => {
    const generation = ++generationRef.current;
    const activeResources = resourcesRef.current;

    if (!activeResources) {
      applyState((current) => ({
        ...current,
        phase: "idle",
        error: null,
        activeSession: null,
        isMicMuted: false,
        lastToolkitMessage: current.transcript.length > 0 ? null : "No live voice session is running.",
      }));
      return;
    }

    try {
      await teardownVoiceSession(activeResources, true);
      if (resourcesRef.current === activeResources) {
        resourcesRef.current = null;
      }

      if (!mountedRef.current || generationRef.current !== generation) {
        return;
      }

      setState((current) => ({
        ...current,
        phase: "idle",
        error: null,
        activeSession: null,
        isMicMuted: false,
        lastToolkitMessage: current.transcript.length > 0 ? null : "No live voice session is running.",
      }));
    } catch (error) {
      if (!mountedRef.current || generationRef.current !== generation) {
        return;
      }

      const message =
        error instanceof Error ? error.message : "Failed to stop the current voice session.";
      setState((current) => ({
        ...current,
        phase: "error",
        error: message,
        lastToolkitMessage: message,
      }));
    }
  });

  const toggleMute = useEffectEvent(async () => {
    const micTrack = resourcesRef.current?.micTrack;
    if (!micTrack) {
      return;
    }

    const nextMuted = !stateRef.current.isMicMuted;
    try {
      await micTrack.setEnabled(!nextMuted);
      applyState((current) => ({
        ...current,
        isMicMuted: nextMuted,
        lastToolkitMessage: nextMuted ? "Microphone muted." : "Microphone unmuted.",
      }));
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to toggle microphone state.";
      applyState((current) => ({
        ...current,
        error: message,
        lastToolkitMessage: message,
      }));
    }
  });

  useEffect(() => {
    mountedRef.current = true;

    const handlePageHide = () => {
      const bindingId = resourcesRef.current?.bindingId;
      if (bindingId) {
        stopConnectorSessionBeacon(bindingId);
      }
    };

    window.addEventListener("pagehide", handlePageHide);
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      handlePageHide();
      window.removeEventListener("pagehide", handlePageHide);
      void teardownVoiceSession(resourcesRef.current, false);
      resourcesRef.current = null;
    };
  }, []);

  return {
    state,
    start,
    stop,
    toggleMute,
  };
}
