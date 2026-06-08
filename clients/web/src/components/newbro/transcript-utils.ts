import type { ConnectorActivateResponse } from "../../lib/connector-client";
import type { VoiceTranscriptTurn } from "../../lib/voice-runtime";

export function formatTranscriptTime(value: string | null) {
  if (!value) {
    return null;
  }

  const date = new Date(value);
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(
    2,
    "0",
  )}`;
}

function normalizeSpeakerId(value: string | number | null | undefined) {
  if (value === null || value === undefined) {
    return null;
  }

  const raw = String(value).trim();
  return raw.length > 0 ? raw : null;
}

export function resolveTranscriptSpeakerLabel(
  item: VoiceTranscriptTurn,
  transcriptSession: ConnectorActivateResponse | null,
) {
  const metadataObject =
    item.metadata && typeof item.metadata.object === "string"
      ? item.metadata.object.toLowerCase()
      : null;

  if (metadataObject?.includes("agent")) {
    return "NewBro";
  }
  if (metadataObject?.includes("user")) {
    return "Me";
  }

  const transcriptUid = normalizeSpeakerId(item.uid);
  const agentUid = normalizeSpeakerId(transcriptSession?.agent.uid);
  const userUid = normalizeSpeakerId(transcriptSession?.uid);
  const diagnosticUserUid = normalizeSpeakerId(transcriptSession?.diagnostics.rtc_uid);

  if (transcriptUid && agentUid && transcriptUid === agentUid) {
    return "NewBro";
  }
  if (
    transcriptUid &&
    ((userUid && transcriptUid === userUid) ||
      (diagnosticUserUid && transcriptUid === diagnosticUserUid))
  ) {
    return "Me";
  }

  return "Speaker";
}

export function isLocalSpeaker(
  item: VoiceTranscriptTurn,
  transcriptSession: ConnectorActivateResponse | null,
) {
  return resolveTranscriptSpeakerLabel(item, transcriptSession) === "Me";
}
