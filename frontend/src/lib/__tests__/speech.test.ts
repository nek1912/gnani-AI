import { describe, it, expect, vi, beforeEach } from "vitest";
import * as api from "../api";
import {
  partitionRuns,
  hasVoice,
  pickVoice,
  speakSegments,
  createSpeechService,
  encodeWav,
  bytesToBase64,
} from "../speech";

// Minimal WAV hex (doesn't need to be valid audio for the test; we stub Audio).
const FAKE_HEX = "000000";

beforeEach(() => {
  vi.resetAllMocks();
  // Stub Audio so play() resolves and onended fires, letting playAzure settle.
  class StubAudio {
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    constructor(_src?: string) {
      void _src;
    }
    play() {
      Promise.resolve().then(() => this.onended?.());
      return Promise.resolve();
    }
  }
  (globalThis as unknown as { Audio: typeof StubAudio }).Audio = StubAudio;
});

describe("partitionRuns", () => {
  it("merges contiguous same-language segments", () => {
    const out = partitionRuns([
      { text: "Hello ", language: "en" },
      { text: "world", language: "en" },
      { text: "नमस्ते", language: "hi" },
    ]);
    expect(out).toEqual([
      { text: "Hello world", language: "en" },
      { text: "नमस्ते", language: "hi" },
    ]);
  });

  it("returns empty array for empty input", () => {
    expect(partitionRuns([])).toEqual([]);
  });
});

describe("hasVoice / pickVoice", () => {
  it("returns false/undefined when no speechSynthesis (jsdom/node)", () => {
    expect(hasVoice("en")).toBe(false);
    expect(pickVoice("hi")).toBeUndefined();
  });
});

describe("speakSegments", () => {
  it("sends a single run to the backend and resolves", async () => {
    const spy = vi
      .spyOn(api, "fetchVoiceSpeak")
      .mockResolvedValue({ audio: FAKE_HEX, language: "hi" });

    await speakSegments([{ text: "नमस्ते", language: "hi" }]);

    expect(spy).toHaveBeenCalledWith([{ text: "नमस्ते", language: "hi" }]);
  });

  it("batches every language run into a single backend call", async () => {
    const spy = vi
      .spyOn(api, "fetchVoiceSpeak")
      .mockResolvedValue({ audio: FAKE_HEX, language: "en" });

    await speakSegments([
      { text: "Hello ", language: "en" },
      { text: "world", language: "en" },
      { text: "नमस्ते", language: "hi" },
    ]);

    /*
     * The whole answer is one request. partitionRuns merges the two English
     * segments into a single run, and the backend's /voice/speak accepts a
     * `segments` array and handles segmentation itself -- one network round
     * trip per utterance, not one per language run. The previous expectation of
     * two calls encoded an older per-run design that the code no longer uses.
     */
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith([
      { text: "Hello world", language: "en" },
      { text: "नमस्ते", language: "hi" },
    ]);
  });
});

describe("speakSegments cancellation", () => {
  // Stub Audio whose play() resolves but whose onended NEVER fires — this
  // reproduces the dangling-promise bug where pause() does not settle the
  // awaiting playAzure promise.
  beforeEach(() => {
    vi.resetAllMocks();
    class NonEndingAudio {
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(_src?: string) {
        void _src;
      }
      play() {
        return Promise.resolve();
      }
    }
    (globalThis as unknown as { Audio: typeof NonEndingAudio }).Audio =
      NonEndingAudio;
  });

  it("settles the in-flight Azure promise when a newer call cancels it", async () => {
    vi.spyOn(api, "fetchVoiceSpeak").mockResolvedValue({
      audio: FAKE_HEX,
      language: "hi",
    });

    const first = speakSegments([{ text: "नमस्ते", language: "hi" }]);
    // Second call cancels the first via stopAllPlayback().
    speakSegments([{ text: "अलविदा", language: "hi" }]);

    await expect(first).resolves.toBeUndefined();
  });

  it("settles the in-flight Azure promise when stopSpeaking is called", async () => {
    vi.spyOn(api, "fetchVoiceSpeak").mockResolvedValue({
      audio: FAKE_HEX,
      language: "hi",
    });

    const first = speakSegments([{ text: "नमस्ते", language: "hi" }]);
    createSpeechService().stopSpeaking();

    await expect(first).resolves.toBeUndefined();
  });
});

describe("WAV encoding and base64", () => {
  it("encodes PCM Float32 samples into a valid 44-byte RIFF/WAV header", () => {
    const samples = new Float32Array([0, 0.5, -0.5, 1, -1]);
    const wav = encodeWav(samples, 16000);
    expect(wav.length).toBe(44 + samples.length * 2);

    const textDecoder = new TextDecoder();
    expect(textDecoder.decode(wav.subarray(0, 4))).toBe("RIFF");
    expect(textDecoder.decode(wav.subarray(8, 12))).toBe("WAVE");
    expect(textDecoder.decode(wav.subarray(12, 16))).toBe("fmt ");
    expect(textDecoder.decode(wav.subarray(36, 40))).toBe("data");
  });

  it("converts bytes to base64 correctly", () => {
    const bytes = new Uint8Array([72, 101, 108, 108, 111]); // "Hello"
    const b64 = bytesToBase64(bytes);
    expect(b64).toBe("SGVsbG8=");
  });
});

describe("createSpeechService().listen STT", () => {
  it("falls back to browser SpeechRecognition or reports error when no getUserMedia", () => {
    const onError = vi.fn();
    const service = createSpeechService();
    const stop = service.listen("hi", () => {}, onError);
    expect(typeof stop).toBe("function");
    stop();
  });

  it("records PCM audio via getUserMedia and calls fetchVoiceTranscribe", async () => {
    const onTranscript = vi.fn();
    const spy = vi
      .spyOn(api, "fetchVoiceTranscribe")
      .mockResolvedValue({ text: "नमस्ते किसान", language: "hi" });

    // Mock mediaDevices.getUserMedia and Web Audio API
    let capturedProcessCallback: ((e: any) => void) | null = null;
    const mockTrack = { stop: vi.fn() };
    const mockStream = { getTracks: () => [mockTrack] };

    const mockProcessor = {
      connect: vi.fn(),
      disconnect: vi.fn(),
      set onaudioprocess(fn: any) {
        capturedProcessCallback = fn;
      },
    };
    const mockSource = {
      connect: vi.fn(),
      disconnect: vi.fn(),
    };
    class MockAudioContext {
      sampleRate = 16000;
      state = "running";
      createMediaStreamSource = vi.fn().mockReturnValue(mockSource);
      createScriptProcessor = vi.fn().mockReturnValue(mockProcessor);
      destination = {};
      close = vi.fn();
    }

    const originalMediaDevices = navigator.mediaDevices;
    const originalAudioContext = window.AudioContext;

    Object.defineProperty(navigator, "mediaDevices", {
      value: {
        getUserMedia: vi.fn().mockResolvedValue(mockStream),
      },
      configurable: true,
    });
    (window as any).AudioContext = MockAudioContext;

    try {
      const service = createSpeechService();
      const stop = service.listen("hi", onTranscript);

      // Wait for getUserMedia promise to resolve
      await Promise.resolve();
      await Promise.resolve();

      expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled();

      // Simulate audio processing (loud speech sample)
      const speechData = new Float32Array(4096);
      for (let i = 0; i < 4096; i++) {
        speechData[i] = 0.5 * Math.sin(i);
      }
      if (capturedProcessCallback) {
        (capturedProcessCallback as any)({
          inputBuffer: { getChannelData: () => speechData },
        });
      }

      // Stop recording
      stop();

      // Wait for async finalize and fetchVoiceTranscribe
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();

      expect(spy).toHaveBeenCalled();
      expect(onTranscript).toHaveBeenCalledWith("नमस्ते किसान");
      expect(mockTrack.stop).toHaveBeenCalled();
    } finally {
      Object.defineProperty(navigator, "mediaDevices", {
        value: originalMediaDevices,
        configurable: true,
      });
      window.AudioContext = originalAudioContext;
    }
  });
});
