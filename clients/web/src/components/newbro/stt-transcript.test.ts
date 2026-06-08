import { describe, expect, it } from "vitest";
import { gzip } from "pako";
import { agoraSttTextMessage, extractTranscriptText } from "./stt-transcript";

function encodeAgoraSttMessage(payload: Record<string, unknown>): Uint8Array {
  return agoraSttTextMessage.encode(agoraSttTextMessage.create(payload)).finish();
}

describe("extractTranscriptText", () => {
  it("extracts plain string transcripts", () => {
    expect(extractTranscriptText("hello there")).toEqual({ text: "hello there", final: true, source: "plain-text" });
  });

  it("extracts JSON byte transcripts", () => {
    const bytes = new TextEncoder().encode(JSON.stringify({ text: "json bytes", final: true }));
    expect(extractTranscriptText(bytes)).toMatchObject({ text: "json bytes", final: true });
  });

  it("extracts gzipped JSON byte transcripts", () => {
    const bytes = gzip(new TextEncoder().encode(JSON.stringify({ text: "gzipped json", final: true })));
    expect(extractTranscriptText(bytes)).toMatchObject({ text: "gzipped json", final: true });
  });

  it("extracts plain object transcripts", () => {
    expect(extractTranscriptText({ words: [{ text: "plain" }, { text: "object" }], isFinal: true })).toMatchObject({
      text: "plain object",
      final: true,
      source: "object-words",
    });
  });

  it("extracts nested result transcripts", () => {
    expect(extractTranscriptText({ result: { text: "nested interim", isFinal: false } })).toMatchObject({
      text: "nested interim",
      final: false,
    });
    expect(extractTranscriptText({ result: { text: "nested final", isFinal: true } })).toMatchObject({
      text: "nested final",
      final: true,
    });
  });

  it("extracts nested data transcripts", () => {
    expect(extractTranscriptText({ data: JSON.stringify({ text: "json data", final: true }) })).toMatchObject({
      text: "json data",
      final: true,
    });
    expect(extractTranscriptText({ data: { words: [{ word: "word" }, { word: "data", final: true }], final: true } })).toMatchObject({
      text: "word data",
      final: true,
    });
  });

  it("extracts official JSON transcript wrappers", () => {
    expect(extractTranscriptText({ transcript: { language: "zh-CN", text: "你好", isFinal: false } })).toEqual({
      text: "你好",
      final: false,
      language: "zh-CN",
      culture: "zh-CN",
      source: "transcript-wrapper",
    });
    expect(extractTranscriptText({ transcript: { language: "zh-CN", text: "你好世界", isFinal: true } })).toEqual({
      text: "你好世界",
      final: false,
      language: "zh-CN",
      culture: "zh-CN",
      source: "transcript-wrapper",
    });
  });

  it("extracts original transcript from translation wrappers", () => {
    expect(extractTranscriptText({
      translation: {
        original_transcript: { language: "zh-CN", text: "原始中文", isFinal: true },
        translated_transcript: { language: "en-US", text: "original Chinese", isFinal: true },
      },
    })).toEqual({ text: "原始中文", final: false, language: "zh-CN", culture: "zh-CN", source: "translation-original" });
  });

  it("normalizes official JSON transcript timing aliases", () => {
    expect(extractTranscriptText({
      transcript: {
        uid: 222,
        language: "zh-CN",
        text: "北选手",
        isFinal: false,
        offset: 1_751_438_272_384,
        duration: 760,
        textTs: 1_751_438_273_939,
      },
    })).toMatchObject({
      text: "北选手",
      final: false,
      language: "zh-CN",
      culture: "zh-CN",
      uid: 222,
      time: 1_751_438_272_384,
      durationMs: 760,
      textTs: 1_751_438_273_939,
    });
  });

  it("ignores translated transcript wrappers without original text", () => {
    expect(extractTranscriptText({
      translation: {
        translated_transcript: { language: "en-US", text: "translated English", isFinal: true },
      },
    })).toBeNull();
  });

  it("extracts interim Agora protobuf transcripts", () => {
    const bytes = encodeAgoraSttMessage({
      data_type: "transcribe",
      words: [{ text: "interim text", isFinal: false }],
      end_of_segment: false,
    });
    expect(extractTranscriptText(bytes)).toMatchObject({ text: "interim text", final: false, source: "protobuf-words" });
  });

  it("extracts Agora protobuf transcript timing metadata", () => {
    const bytes = encodeAgoraSttMessage({
      data_type: "transcribe",
      culture: "zh-CN",
      uid: 101,
      seqnum: 7,
      time: 1_000,
      starttime: 900,
      offtime: 1_200,
      duration_ms: 200,
      text_ts: 1_250,
      sentence_end_index: 3,
      words: [{ text: "metadata", startMs: 10, durationMs: 90, isFinal: true, confidence: 0.875 }],
      end_of_segment: false,
    });
    expect(extractTranscriptText(bytes)).toMatchObject({
      text: "metadata",
      final: false,
      source: "protobuf-words",
      uid: 101,
      seqnum: 7,
      time: 1_000,
      starttime: 900,
      offtime: 1_200,
      durationMs: 200,
      dataType: "transcribe",
      culture: "zh-CN",
      textTs: 1_250,
      sentenceEndIndex: 3,
      words: [{ text: "metadata", startMs: 10, durationMs: 90, isFinal: true, confidence: 0.875 }],
    });
  });

  it("does not treat stable protobuf words as a final segment", () => {
    const bytes = encodeAgoraSttMessage({
      data_type: "transcribe",
      words: [
        { text: "stable", isFinal: true },
        { text: "candidate", isFinal: true },
      ],
      end_of_segment: false,
    });
    expect(extractTranscriptText(bytes)).toMatchObject({ text: "stablecandidate", final: false, source: "protobuf-words" });
  });

  it("extracts official protobuf original transcript from translation payloads", () => {
    const bytes = encodeAgoraSttMessage({
      data_type: "translate",
      time: 1_000,
      duration_ms: 770,
      text_ts: 1_100,
      trans: [{ isFinal: true, lang: "en-US", texts: ["translated English"] }],
      original_transcript: {
        culture: "zh-CN",
        words: [{ text: "原始中文", isFinal: true }],
      },
    });
    expect(extractTranscriptText(bytes)).toMatchObject({
      text: "原始中文",
      final: false,
      language: "zh-CN",
      culture: "zh-CN",
      source: "protobuf-original-transcript",
      time: 1_000,
      durationMs: 770,
      textTs: 1_100,
    });
  });

  it("extracts final Agora protobuf transcripts", () => {
    const bytes = encodeAgoraSttMessage({
      data_type: "transcribe",
      words: [
        { text: "final", isFinal: true },
        { text: "text", isFinal: true },
      ],
      end_of_segment: true,
    });
    expect(extractTranscriptText(bytes)).toMatchObject({ text: "finaltext", final: true, source: "protobuf-words" });
  });

  it("extracts only original words from Agora protobuf with translations", () => {
    const bytes = encodeAgoraSttMessage({
      data_type: "transcribe",
      words: [{ text: "原始中文", isFinal: true }],
      trans: [{ isFinal: true, lang: "en-US", texts: ["translated English"] }],
      end_of_segment: true,
    });
    expect(extractTranscriptText(bytes)).toMatchObject({ text: "原始中文", final: true, source: "protobuf-words" });
  });

  it("ignores Agora protobuf translation-only transcripts", () => {
    const bytes = encodeAgoraSttMessage({
      data_type: "transcribe",
      trans: [{ isFinal: true, lang: "en-US", texts: ["translated English"] }],
      end_of_segment: true,
    });
    expect(extractTranscriptText(bytes)).toBeNull();
  });

  it("extracts gzipped Agora protobuf transcripts", () => {
    const bytes = gzip(encodeAgoraSttMessage({
      data_type: "transcribe",
      words: [{ text: "gzipped", isFinal: true }],
      end_of_segment: true,
    }));
    expect(extractTranscriptText(bytes)).toMatchObject({ text: "gzipped", final: true, source: "protobuf-words" });
  });

  it("ignores byte payloads that are not JSON or supported protobuf transcripts", () => {
    expect(extractTranscriptText(new Uint8Array([0, 1, 2, 80, 81, 82, 3]))).toBeNull();
    expect(extractTranscriptText(new TextEncoder().encode("clean utf8 transcript"))).toBeNull();
  });

  it("returns null for empty or unrecognized payloads", () => {
    expect(extractTranscriptText("")).toBeNull();
    expect(extractTranscriptText({ nope: true })).toBeNull();
    expect(extractTranscriptText(new Uint8Array([0]))).toBeNull();
    expect(extractTranscriptText(new Uint8Array([0x1f, 0x8b, 0]))).toBeNull();
  });
});
