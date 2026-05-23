import { stopConnectorSession } from "./connector-client";

export type VoiceTranscriptTurn = {
  turn_id?: string | number;
  uid?: string | number;
  text?: string;
  status?: string;
  metadata?: Record<string, unknown> | null;
};

export type ActiveVoiceResources = {
  bindingId: string;
  rtcClient: any;
  micTrack: any;
  rtmClient: any;
  voiceAi: any;
};

export async function loadAgoraBrowserStack() {
  const agoraRtcModule = await import("agora-rtc-sdk-ng");
  const agoraRtmModule = await import("agora-rtm");
  const toolkitModule = await import("agora-agent-client-toolkit");
  return {
    AgoraRTC: agoraRtcModule.default,
    AgoraRTM: agoraRtmModule.default,
    AgoraVoiceAI: toolkitModule.AgoraVoiceAI,
    AgoraVoiceAIEvents: toolkitModule.AgoraVoiceAIEvents,
    TranscriptHelperMode: toolkitModule.TranscriptHelperMode,
  };
}

export async function teardownVoiceSession(
  resources: ActiveVoiceResources | null,
  notifyBackend: boolean,
) {
  if (!resources) {
    return;
  }

  try {
    resources.voiceAi?.unsubscribe();
  } catch {}

  try {
    resources.voiceAi?.destroy();
  } catch {}

  try {
    resources.micTrack?.stop();
    resources.micTrack?.close();
  } catch {}

  try {
    await resources.rtmClient?.logout();
  } catch {}

  try {
    await resources.rtcClient?.leave();
  } catch {}

  if (notifyBackend && resources.bindingId) {
    await stopConnectorSession(resources.bindingId);
  }
}
