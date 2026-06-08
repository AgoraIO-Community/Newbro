import type { BroTimelineMessage } from "../types";

/** The display text of a timeline message: trimmed transcript for audio, trimmed text otherwise. */
export function timelineMessageText(message: BroTimelineMessage | null): string {
  if (!message) return "";
  return (message.kind === "audio" ? message.transcript : message.text)?.trim() ?? "";
}
