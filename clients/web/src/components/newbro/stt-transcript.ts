import protobuf from "protobufjs/light";
import { ungzip } from "pako";

export type ExtractedSttWord = {
  text: string;
  startMs?: number;
  durationMs?: number;
  isFinal?: boolean;
  confidence?: number;
};

export type ExtractedSttTranscript = {
  text: string;
  final: boolean;
  language?: string;
  source?: string;
  uid?: string | number;
  seqnum?: number;
  time?: number;
  starttime?: number;
  offtime?: number;
  durationMs?: number;
  dataType?: string;
  culture?: string;
  textTs?: number;
  sentenceEndIndex?: number;
  words?: ExtractedSttWord[];
};

export type SttTranscriptDebugPayload = {
  kind: "string" | "bytes" | "object" | "unknown";
  payload: unknown;
};

const sttRoot = protobuf.Root.fromJSON({
  nested: {
    Agora: {
      nested: {
        SpeechToText: {
          nested: {
            Text: {
              fields: {
                // Reserved by the current official SttMessage.proto, retained
                // so older deployed bots can still decode during rollout.
                vendor: { type: "int32", id: 1 },
                version: { type: "int32", id: 2 },
                seqnum: { type: "int32", id: 3 },
                uid: { type: "int64", id: 4 },
                flag: { type: "int32", id: 5 },
                time: { type: "int64", id: 6 },
                lang: { type: "int32", id: 7 },
                starttime: { type: "int32", id: 8 },
                offtime: { type: "int32", id: 9 },
                words: { rule: "repeated", type: "Word", id: 10 },
                end_of_segment: { type: "bool", id: 11 },
                duration_ms: { type: "int32", id: 12 },
                data_type: { type: "string", id: 13 },
                trans: { rule: "repeated", type: "Translation", id: 14 },
                culture: { type: "string", id: 15 },
                text_ts: { type: "int64", id: 16 },
                sentence_end_index: { type: "int32", id: 17 },
                original_transcript: { type: "OriginalTranscript", id: 18 },
              },
            },
            Word: {
              fields: {
                text: { type: "string", id: 1 },
                startMs: { type: "int32", id: 2 },
                durationMs: { type: "int32", id: 3 },
                isFinal: { type: "bool", id: 4 },
                confidence: { type: "double", id: 5 },
              },
            },
            Translation: {
              fields: {
                isFinal: { type: "bool", id: 1 },
                lang: { type: "string", id: 2 },
                texts: { rule: "repeated", type: "string", id: 3 },
              },
            },
            OriginalTranscript: {
              fields: {
                culture: { type: "string", id: 1 },
                words: { rule: "repeated", type: "Word", id: 2 },
              },
            },
          },
        },
      },
    },
  },
});

export const agoraSttTextMessage = sttRoot.lookupType("Agora.SpeechToText.Text");

const textDecoder = new TextDecoder();

export function extractTranscriptText(payload: unknown): ExtractedSttTranscript | null {
  if (typeof payload === "string") {
    return extractStringTranscript(payload);
  }
  const bytes = payloadToBytes(payload);
  if (bytes) {
    return extractBytesTranscript(bytes);
  }
  if (!payload || typeof payload !== "object") return null;
  return extractRecordTranscript(payload as Record<string, any>);
}

export function describeTranscriptPayload(payload: unknown): SttTranscriptDebugPayload {
  if (typeof payload === "string") {
    return { kind: "string", payload };
  }
  const bytes = payloadToBytes(payload);
  if (bytes) {
    return { kind: "bytes", payload: describeBytesTranscript(bytes) ?? bytes };
  }
  if (payload && typeof payload === "object") {
    return { kind: "object", payload };
  }
  return { kind: "unknown", payload };
}

export function describeProtobufTranscriptPayload(payload: unknown): unknown | null {
  const bytes = payloadToBytes(payload);
  if (!bytes) return null;
  return describeProtobufBytesTranscript(bytes);
}

function describeBytesTranscript(bytes: Uint8Array): unknown | null {
  const inflated = inflateGzipPayload(bytes);
  if (inflated) {
    return { compression: "gzip", payload: describeBytesTranscript(inflated) ?? inflated };
  }
  try {
    const decoded = textDecoder.decode(bytes).trim();
    if (decoded && (decoded.startsWith("{") || decoded.startsWith("["))) {
      return JSON.parse(decoded);
    }
  } catch {}
  try {
    return agoraSttTextMessage.toObject(agoraSttTextMessage.decode(bytes), {
      defaults: false,
      longs: Number,
    });
  } catch {
    return null;
  }
}

function describeProtobufBytesTranscript(bytes: Uint8Array): unknown | null {
  const inflated = inflateGzipPayload(bytes);
  if (inflated) {
    return { compression: "gzip", payload: describeProtobufBytesTranscript(inflated) };
  }
  try {
    return agoraSttTextMessage.toObject(agoraSttTextMessage.decode(bytes), {
      defaults: false,
      longs: Number,
    });
  } catch {
    return null;
  }
}

function extractStringTranscript(payload: string): ExtractedSttTranscript | null {
  const trimmed = payload.trim();
  if (!trimmed) return null;
  try {
    return extractTranscriptText(JSON.parse(trimmed));
  } catch {
    return { text: trimmed, final: true, source: "plain-text" };
  }
}

function extractBytesTranscript(bytes: Uint8Array): ExtractedSttTranscript | null {
  const inflated = inflateGzipPayload(bytes);
  if (inflated) {
    return extractBytesTranscript(inflated);
  }
  return decodeJsonBytesTranscript(bytes) ?? decodeProtobufTranscript(bytes);
}

function inflateGzipPayload(bytes: Uint8Array): Uint8Array | null {
  if (bytes.byteLength < 2 || bytes[0] !== 0x1f || bytes[1] !== 0x8b) return null;
  try {
    return ungzip(bytes);
  } catch {
    return null;
  }
}

function decodeJsonBytesTranscript(bytes: Uint8Array): ExtractedSttTranscript | null {
  try {
    const decoded = textDecoder.decode(bytes).trim();
    if (!decoded) return null;
    if (decoded.startsWith("{") || decoded.startsWith("[")) {
      const parsed = extractTranscriptText(JSON.parse(decoded));
      if (parsed) return parsed;
    }
  } catch {}
  return null;
}

function decodeProtobufTranscript(bytes: Uint8Array): ExtractedSttTranscript | null {
  try {
    const decoded = agoraSttTextMessage.toObject(agoraSttTextMessage.decode(bytes), {
      defaults: false,
      longs: Number,
    }) as Record<string, any>;
    const originalTranscript = readRecordField(decoded, "original_transcript", "originalTranscript");
    const originalWords = Array.isArray(originalTranscript?.words) ? originalTranscript.words : null;
    const words = originalWords ?? (Array.isArray(decoded.words) ? decoded.words : []);
    const wordText = words
      .map((word) => (typeof word?.text === "string" ? word.text.trim() : ""))
      .filter(Boolean)
      .join("")
      .trim();
    if (!wordText) return null;
    const originalCulture = readStringField(originalTranscript ?? {}, "culture");
    return {
      text: wordText,
      final: readBoolField(decoded, "end_of_segment", "endOfSegment") === true,
      source: originalWords ? "protobuf-original-transcript" : "protobuf-words",
      ...extractTranscriptMetadata(decoded),
      ...(originalCulture ? { language: originalCulture, culture: originalCulture } : {}),
      words: extractWordMetadata(words),
    };
  } catch {
    return null;
  }
}

function extractRecordTranscript(record: Record<string, any>): ExtractedSttTranscript | null {
  const wrappedTranscript = extractWrappedTranscript(record.transcript);
  if (wrappedTranscript) return wrappedTranscript;
  const originalTranscript = extractWrappedTranscript(record.translation?.original_transcript, "translation-original");
  if (originalTranscript) return originalTranscript;
  const nested = [record.result, record.data, record.payload].find((item) => item != null);
  if (nested != null && nested !== record) {
    const parsed = extractTranscriptText(nested);
    if (parsed) return parsed;
  }
  const candidates = [
    record.text,
    record.transcript,
    record.message,
    extractWordsText(record.words),
  ];
  const text = candidates.find((item) => typeof item === "string" && item.trim());
  if (!text) return null;
  const final = isFinalRecord(record);
  const words = Array.isArray(record.words) ? extractWordMetadata(record.words) : undefined;
  return { text: text.trim(), final, source: Array.isArray(record.words) ? "object-words" : "object", ...extractTranscriptMetadata(record), ...(words ? { words } : {}) };
}

function extractWrappedTranscript(transcript: unknown, source = "transcript-wrapper"): ExtractedSttTranscript | null {
  if (!transcript || typeof transcript !== "object") return null;
  const record = transcript as Record<string, any>;
  if (typeof record.text !== "string" || !record.text.trim()) return null;
  const language = typeof record.language === "string" ? record.language : typeof record.lang === "string" ? record.lang : undefined;
  return {
    text: record.text.trim(),
    final: readBoolField(record, "end_of_segment", "endOfSegment") === true,
    language,
    source,
    ...extractTranscriptMetadata(record),
    ...(language ? { culture: language } : {}),
  };
}

function extractWordsText(words: unknown): string | null {
  if (!Array.isArray(words)) return null;
  const text = words
    .map((word) => {
      if (typeof word === "string") return word;
      if (!word || typeof word !== "object") return "";
      const record = word as Record<string, any>;
      return record.text ?? record.word ?? "";
    })
    .filter((item) => typeof item === "string" && item.trim())
    .join(" ")
    .trim();
  return text || null;
}

function extractWordMetadata(words: unknown[]): ExtractedSttWord[] {
  return words
    .map((word): ExtractedSttWord | null => {
      if (!word || typeof word !== "object") return null;
      const record = word as Record<string, any>;
      const text = typeof record.text === "string" ? record.text.trim() : typeof record.word === "string" ? record.word.trim() : "";
      if (!text) return null;
      return {
        text,
        startMs: readNumberField(record, "start_ms", "startMs"),
        durationMs: readNumberField(record, "duration_ms", "durationMs"),
        isFinal: readBoolField(record, "is_final", "isFinal", "final"),
        confidence: readNumberField(record, "confidence"),
      };
    })
    .filter((word): word is ExtractedSttWord => word != null);
}

function isFinalRecord(record: Record<string, any>): boolean {
  const status = String(record.status ?? record.type ?? record.state ?? "").toLowerCase();
  if (record.final === true || record.isFinal === true || readBoolField(record, "end_of_segment", "endOfSegment") === true) return true;
  if (["final", "end", "complete", "completed"].includes(status)) return true;
  if (Array.isArray(record.words) && record.words.length > 0) {
    return record.words.every((word: any) => word?.isFinal === true || word?.final === true);
  }
  return false;
}

function extractTranscriptMetadata(record: Record<string, any>): Partial<ExtractedSttTranscript> {
  const language = readStringField(record, "language", "lang", "culture");
  return compactTranscriptMetadata({
    uid: readUidField(record),
    seqnum: readNumberField(record, "seqnum"),
    time: readNumberField(record, "time", "offset"),
    starttime: readNumberField(record, "starttime", "startTime"),
    offtime: readNumberField(record, "offtime", "offTime"),
    durationMs: readNumberField(record, "duration_ms", "durationMs", "duration"),
    dataType: readStringField(record, "data_type", "dataType"),
    culture: language,
    language,
    textTs: readNumberField(record, "text_ts", "textTs"),
    sentenceEndIndex: readNumberField(record, "sentence_end_index", "sentenceEndIndex"),
  });
}

function compactTranscriptMetadata(metadata: Partial<ExtractedSttTranscript>): Partial<ExtractedSttTranscript> {
  return Object.fromEntries(Object.entries(metadata).filter(([, value]) => value !== undefined)) as Partial<ExtractedSttTranscript>;
}

function readUidField(record: Record<string, any>): string | number | undefined {
  const uid = record.uid;
  if (typeof uid === "string" && uid.trim()) return uid;
  if (typeof uid === "number" && Number.isFinite(uid)) return uid;
  return undefined;
}

function readNumberField(record: Record<string, any>, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return undefined;
}

function readStringField(record: Record<string, any>, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return undefined;
}

function readBoolField(record: Record<string, any>, ...keys: string[]): boolean | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "boolean") return value;
  }
  return undefined;
}

function readRecordField(record: Record<string, any>, ...keys: string[]): Record<string, any> | undefined {
  for (const key of keys) {
    const value = record[key];
    if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, any>;
  }
  return undefined;
}

function payloadToBytes(payload: unknown): Uint8Array | null {
  if (payload instanceof Uint8Array) return payload;
  if (payload instanceof ArrayBuffer) return new Uint8Array(payload);
  if (ArrayBuffer.isView(payload)) {
    return new Uint8Array(payload.buffer, payload.byteOffset, payload.byteLength);
  }
  return null;
}
