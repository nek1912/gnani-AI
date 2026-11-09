import { fetchVoiceSpeak, fetchVoiceTranscribe, type SpeechSegment } from "./api";
import { apiFetch } from "./backend";

export type { SpeechSegment };

export interface SpeechService {
  supported: boolean;
  listen: (
    locale: string,
    onTranscript: (text: string) => void,
    onError?: (err: string) => void,
  ) => () => void;
  speak: (text: string, locale: string) => Promise<void>;
  stopSpeaking: () => void;
}

let currentAudio: HTMLAudioElement | null = null;
let currentObjectUrl: string | null = null;

function stopAll() {
  if (currentAudio) {
    try {
      currentAudio.pause();
    } catch {
      /* noop */
    }
    currentAudio = null;
  }

  if (currentObjectUrl) {
    try {
      URL.revokeObjectURL(currentObjectUrl);
    } catch {
      /* noop */
    }
    currentObjectUrl = null;
  }

  if (typeof window !== "undefined" && window.speechSynthesis) {
    try {
      window.speechSynthesis.cancel();
    } catch {
      /* noop */
    }
  }
}

// Monotonic token for cancelling in-flight playback when a newer request starts
// or the user stops. Incrementing this invalidates any pending utterance/audio.
let _speakToken = 0;
let _activeAudio: HTMLAudioElement | null = null;
let _activeAudioResolve: (() => void) | null = null;

function stopAllPlayback(): void {
  stopAll();
  _speakToken++;

  if (_activeAudio) {
    try {
      _activeAudio.pause();
    } catch {
      /* noop */
    }
    _activeAudio = null;
  }

  if (_activeAudioResolve) {
    const resolve = _activeAudioResolve;
    _activeAudioResolve = null;
    resolve();
  }
}

export function hasVoice(lang: string): boolean {
  if (typeof window === "undefined" || !window.speechSynthesis) return false;

  const voices = window.speechSynthesis.getVoices();
  const prefix = lang === "en" ? "en" : lang;

  return voices.some((v) => v.lang.startsWith(prefix));
}

export function pickVoice(lang: string): SpeechSynthesisVoice | undefined {
  if (typeof window === "undefined" || !window.speechSynthesis) return undefined;

  const voices = window.speechSynthesis.getVoices();
  const prefix = lang === "en" ? "en" : lang;

  return voices.find((v) => v.lang.startsWith(prefix));
}

export function partitionRuns(segments: SpeechSegment[]): SpeechSegment[] {
  const runs: SpeechSegment[] = [];

  for (const seg of segments) {
    const last = runs[runs.length - 1];

    if (last && last.language === seg.language) {
      const sep =
        last.text.endsWith(" ") || seg.text.startsWith(" ") ? "" : " ";
      last.text += sep + seg.text;
    } else {
      runs.push({
        language: seg.language,
        text: seg.text,
      });
    }
  }

  return runs;
}

function hexToBase64(hex: string): string {
  let bin = "";

  for (let i = 0; i < hex.length; i += 2) {
    bin += String.fromCharCode(parseInt(hex.substr(i, 2), 16));
  }

  return btoa(bin);
}

function playBackendAudio(
  audioPayload: string,
  token: number,
): Promise<void> {
  return new Promise((resolve, reject) => {
    if (token !== _speakToken) {
      resolve();
      return;
    }

    let audio: HTMLAudioElement;

    try {
      // If audioPayload is already base64, play directly without expensive hex string conversion
      const base64Data =
        audioPayload.startsWith("UklGR") ||
        audioPayload.length % 2 !== 0 ||
        !/^[0-9a-fA-F]+$/.test(audioPayload)
          ? audioPayload
          : hexToBase64(audioPayload);
      audio = new Audio(`data:audio/wav;base64,${base64Data}`);
    } catch (error) {
      reject(error);
      return;
    }

    _activeAudio = audio;
    _activeAudioResolve = resolve;

    const cleanup = () => {
      audio.onended = null;
      audio.onerror = null;

      if (_activeAudio === audio) {
        _activeAudio = null;
      }

      if (_activeAudioResolve === resolve) {
        _activeAudioResolve = null;
      }
    };

    audio.onended = () => {
      cleanup();
      resolve();
    };

    audio.onerror = () => {
      cleanup();
      reject(new Error("Backend TTS audio playback failed"));
    };

    audio.play().catch((error) => {
      cleanup();
      reject(error);
    });
  });
}

async function speakBackendSegments(
  segments: SpeechSegment[],
  token: number,
): Promise<void> {
  const response = await fetchVoiceSpeak(segments);

  const audioPayload = response.audio_base64 || response.audio;
  if (!audioPayload) {
    throw new Error("Backend TTS returned empty audio");
  }

  /*
   * Bail out BEFORE creating the Audio element.
   *
   * Reading the module-level _speakToken here (instead of using the caller's
   * token) means a call cancelled while the fetch was in flight re-read the NEW
   * token, passed the staleness guard in playBackendAudio, created an Audio
   * element, and then waited forever for an onended that never fires — leaking
   * the element and leaving the caller's promise pending for good.
   */
  if (token !== _speakToken) return;

  await playBackendAudio(audioPayload, token);
}

export async function speakSegments(
  segments: SpeechSegment[],
  opts?: { onToken?: (token: number) => void },
): Promise<void> {
  stopAllPlayback();

  const token = ++_speakToken;
  opts?.onToken?.(token);

  const runs = partitionRuns(segments || []);

  if (runs.length === 0) return;

  /*
   * IMPORTANT:
   *
   * Backend TTS is intentionally the PRIMARY path.
   *
   * /api/voice/speak -> /voice/speak -> VoiceService
   * -> Sarvam TTS -> Azure fallback
   *
   * Browser SpeechSynthesis must NOT be selected merely because Chrome
   * has a local voice available. Doing that would bypass Sarvam entirely.
   */
  try {
    if (token !== _speakToken) return;

    await speakBackendSegments(runs, token);

    if (token !== _speakToken) return;

    return;
  } catch {
    /*
     * Backend unavailable / failed.
     *
     * At this point the backend has already attempted:
     * Sarvam -> Azure.
     *
     * Browser TTS is therefore the final emergency fallback only.
     */
  }

  for (const run of runs) {
    if (token !== _speakToken) return;

    const voice = pickVoice(run.language);

    if (!voice) continue;

    await playBrowser(run.text, voice, token);

    if (token !== _speakToken) return;
  }
}

function playBrowser(
  text: string,
  voice: SpeechSynthesisVoice,
  token: number,
): Promise<void> {
  return new Promise((resolve) => {
    if (
      token !== _speakToken ||
      typeof window === "undefined" ||
      !window.speechSynthesis
    ) {
      resolve();
      return;
    }

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice = voice;
    utterance.lang = voice.lang;

    const done = () => {
      utterance.onend = null;
      utterance.onerror = null;
      resolve();
    };

    utterance.onend = done;
    utterance.onerror = done;

    try {
      window.speechSynthesis.speak(utterance);
    } catch {
      resolve();
    }
  });
}

/**
 * Downsample Float32 PCM audio to strict 16,000 Hz using box-car averaging.
 * Provides clean anti-aliased downsampling regardless of whether hardware records
 * at 44.1kHz, 48kHz, or 16kHz, ensuring optimal recognition accuracy for Gnani Prisma STT.
 */
export function downsampleTo16k(input: Float32Array, inputSampleRate: number): Float32Array {
  if (inputSampleRate === 16000 || input.length === 0) return input;
  const ratio = inputSampleRate / 16000;
  const newLength = Math.max(1, Math.round(input.length / ratio));
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetInput = 0;
  while (offsetResult < result.length) {
    const nextOffsetInput = Math.min(input.length, Math.round((offsetResult + 1) * ratio));
    let accum = 0;
    let count = 0;
    for (let i = offsetInput; i < nextOffsetInput; i++) {
      accum += input[i];
      count++;
    }
    result[offsetResult] = count > 0 ? accum / count : (input[offsetInput] ?? 0);
    offsetResult++;
    offsetInput = nextOffsetInput;
  }
  return result;
}

export function encodeWav(samples: Float32Array, sampleRate: number): Uint8Array {
  const numChannels = 1;
  const bytesPerSample = 2; // 16-bit PCM
  const blockAlign = numChannels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataSize = samples.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  function writeString(offset: number, string: string) {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  }

  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, dataSize, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }

  return new Uint8Array(buffer);
}

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 8192;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode.apply(null, chunk as unknown as number[]);
  }
  return btoa(binary);
}

function listenBrowserSpeech(
  locale: string,
  onTranscript: (text: string) => void,
  onError?: (err: string) => void,
): () => void {
  const isBrowser = typeof window !== "undefined";
  const SpeechRecognition = isBrowser
    ? (window.SpeechRecognition ||
        (window as unknown as { webkitSpeechRecognition?: unknown })
          .webkitSpeechRecognition)
    : undefined;

  if (!SpeechRecognition) {
    onError?.("not-supported");
    return () => {};
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rec = new (SpeechRecognition as any)();
  rec.lang = locale === "en" ? "en-IN" : locale + "-IN";
  rec.interimResults = true;
  rec.maxAlternatives = 1;

  let finalized = false;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  rec.onresult = (e: any) => {
    const text = e.results?.[0]?.[0]?.transcript;
    if (text && e.results[0].isFinal) {
      finalized = true;
      onTranscript(text);
    }
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  rec.onerror = (e: any) => {
    onError?.(e.error || "recognition-error");
  };

  rec.onend = () => {
    if (!finalized) {
      onError?.("no-speech");
    }
  };

  try {
    rec.start();
  } catch (err: unknown) {
    onError?.(err instanceof Error ? err.message : "recognition-error");
    return () => {};
  }

  return () => {
    try {
      rec.stop();
    } catch {
      /* noop */
    }
  };
}

export function createSpeechService(): SpeechService {
  const isBrowser = typeof window !== "undefined";

  return {
    get supported() {
      if (!isBrowser) return false;

      const hasMedia = Boolean(
        navigator.mediaDevices &&
          typeof navigator.mediaDevices.getUserMedia === "function",
      );
      const hasSpeechRec = Boolean(
        window.SpeechRecognition ||
          (window as unknown as { webkitSpeechRecognition?: unknown })
            .webkitSpeechRecognition,
      );

      return (hasMedia || hasSpeechRec) && Boolean(window.speechSynthesis);
    },

    listen(locale, onTranscript, onError?) {
      if (!isBrowser) return () => {};

      const hasMedia = Boolean(
        navigator.mediaDevices &&
          typeof navigator.mediaDevices.getUserMedia === "function",
      );

      if (!hasMedia) {
        return listenBrowserSpeech(locale, onTranscript, onError);
      }

      let stopped = false;
      let finalizing = false;
      let mediaStream: MediaStream | null = null;
      let audioCtx: AudioContext | null = null;
      let processor: ScriptProcessorNode | null = null;
      let source: MediaStreamAudioSourceNode | null = null;
      let muteGain: GainNode | null = null;
      let checkInterval: number | null = null;
      let fallbackCancel: (() => void) | null = null;

      const pcmChunks: Float32Array[] = [];
      let totalSamples = 0;
      let actualSampleRate = 16000;
      let hasSpoken = false;
      let maxRms = 0;
      let lastSpeechTime = Date.now();
      const startTime = Date.now();

      function cleanupAudio() {
        stopped = true;
        if (checkInterval !== null) {
          clearInterval(checkInterval);
          checkInterval = null;
        }
        if (source) {
          try {
            source.disconnect();
          } catch {
            /* noop */
          }
          source = null;
        }
        if (processor) {
          try {
            processor.disconnect();
          } catch {
            /* noop */
          }
          processor = null;
        }
        if (muteGain) {
          try {
            muteGain.disconnect();
          } catch {
            /* noop */
          }
          muteGain = null;
        }
        if (audioCtx && audioCtx.state !== "closed") {
          try {
            audioCtx.close();
          } catch {
            /* noop */
          }
          audioCtx = null;
        }
        if (mediaStream) {
          try {
            mediaStream.getTracks().forEach((track) => track.stop());
          } catch {
            /* noop */
          }
          mediaStream = null;
        }
      }

      async function finalize() {
        if (finalizing) return;
        finalizing = true;
        cleanupAudio();

        if (totalSamples === 0) {
          onError?.("no-speech");
          return;
        }

        const merged = new Float32Array(totalSamples);
        let offset = 0;
        for (const chunk of pcmChunks) {
          merged.set(chunk, offset);
          offset += chunk.length;
        }

        // Downsample to strict 16,000 Hz for optimal Gnani STT accuracy and lower payload latency
        const samples16k = downsampleTo16k(merged, actualSampleRate);
        const durationSec = samples16k.length / 16000;

        // If speech was detected, transcribe it. If no speech was detected and audio is pure silence (< 0.0035 max RMS), report no-speech.
        if (!hasSpoken && (durationSec < 0.35 || maxRms < 0.0035)) {
          onError?.("no-speech");
          return;
        }

        try {
          const wavBytes = encodeWav(samples16k, 16000);
          const base64Audio = bytesToBase64(wavBytes);
          const resp = await fetchVoiceTranscribe(base64Audio, locale);
          if (resp && resp.text && resp.text.trim()) {
            onTranscript(resp.text.trim());
          } else {
            onError?.("no-speech");
          }
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error("Gnani STT failed:", msg);
          onError?.(msg || "transcribe-error");
        }
      }

      // Start recording from user media
      navigator.mediaDevices
        .getUserMedia({
          audio: {
            channelCount: 1,
            sampleRate: 16000,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        })
        .then(async (stream) => {
          if (stopped) {
            stream.getTracks().forEach((t) => t.stop());
            return;
          }
          mediaStream = stream;

          const AudioContextClass =
            window.AudioContext ||
            (window as unknown as { webkitAudioContext: typeof AudioContext })
              .webkitAudioContext;

          try {
            audioCtx = new AudioContextClass({ sampleRate: 16000 });
          } catch {
            audioCtx = new AudioContextClass();
          }

          // Resume audio context if created in suspended state (required by Chrome autoplay policy)
          if (audioCtx.state === "suspended") {
            try {
              await audioCtx.resume();
            } catch {
              /* noop */
            }
          }

          actualSampleRate = audioCtx.sampleRate || 16000;
          source = audioCtx.createMediaStreamSource(stream);
          processor = audioCtx.createScriptProcessor(4096, 1, 1);

          // Route source -> processor -> muteGain -> destination.
          // Muting gain (0.0) ensures Web Audio graph pumps data without playing mic audio
          // into speakers, avoiding speaker-mic acoustic feedback and WebRTC AEC self-cancelling.
          if (typeof audioCtx.createGain === "function") {
            muteGain = audioCtx.createGain();
            muteGain.gain.value = 0;
            source.connect(processor);
            processor.connect(muteGain);
            muteGain.connect(audioCtx.destination);
          } else {
            source.connect(processor);
            processor.connect(audioCtx.destination);
          }

          processor.onaudioprocess = (e) => {
            if (stopped || finalizing) return;
            const input = e.inputBuffer.getChannelData(0);
            const chunk = new Float32Array(input.length);
            chunk.set(input);
            pcmChunks.push(chunk);
            totalSamples += chunk.length;

            let sum = 0;
            for (let i = 0; i < input.length; i++) {
              sum += input[i] * input[i];
            }
            const rms = Math.sqrt(sum / input.length);
            if (rms > maxRms) {
              maxRms = rms;
            }
            // Voice detection threshold: 0.005 captures standard spoken voice reliably
            if (rms > 0.005) {
              hasSpoken = true;
              lastSpeechTime = Date.now();
            }
          };

          // Silence timeout: ~1600ms after user finishes speaking to allow natural speech pauses.
          // 25s hard ceiling bounds recording within Gnani's 30s limit.
          checkInterval = window.setInterval(() => {
            if (stopped || finalizing) return;
            const now = Date.now();
            if (hasSpoken && now - lastSpeechTime > 1600) {
              finalize();
            } else if (now - startTime > 25000) {
              finalize();
            }
          }, 100);
        })
        .catch((err) => {
          if (stopped) return;
          console.warn("getUserMedia failed, falling back to browser SpeechRecognition:", err);
          fallbackCancel = listenBrowserSpeech(locale, onTranscript, onError);
        });

      return () => {
        if (fallbackCancel) {
          fallbackCancel();
          return;
        }
        if (stopped || finalizing) return;
        if (hasSpoken || totalSamples > 0) {
          finalize();
        } else {
          cleanupAudio();
        }
      };
    },

    async speak(text, locale) {
      stopAllPlayback();

      const cleanText = text
        .replace(/\[chunk:[a-f0-9]+\]/g, "")
        .replace(/\*\*([^*]+)\*\*/g, "$1")
        .replace(/\n+/g, ". ")
        .trim();

      if (!cleanText) return;

      /*
       * Normal text follows the same priority:
       *
       * Backend -> Sarvam -> Azure -> browser TTS
       */
      try {
        await speakBackend(cleanText, locale);
        return;
      } catch {
        // Final fallback: browser SpeechSynthesis.
      }

      await speakBrowser(cleanText, locale);
    },

    stopSpeaking() {
      stopAllPlayback();
    },
  };
}

function speakBackend(
  text: string,
  locale: string,
): Promise<void> {
  return new Promise((resolve, reject) => {
    apiFetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language: locale }),
    })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Speak API ${res.status}`);
        }

        /*
         * FastAPI returns { audio: "<hex>", language } as JSON. The removed BFF
         * used to do the hex -> binary conversion here and hand back
         * audio/mpeg, so this used to be res.arrayBuffer(). With the BFF gone
         * the conversion moves to the browser.
         */
        return res.json();
      })
      .then(({ audio: audioHex, audio_base64 }: { audio?: string; audio_base64?: string }) => {
        if (!audioHex && !audio_base64) throw new Error("Backend TTS returned empty audio");

        let bytes: Uint8Array;
        if (audio_base64) {
          const binary = atob(audio_base64);
          bytes = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
          }
        } else {
          bytes = new Uint8Array(audioHex!.length / 2);
          for (let i = 0; i < audioHex!.length; i += 2) {
            bytes[i / 2] = parseInt(audioHex!.substr(i, 2), 16);
          }
        }

        if (bytes.byteLength < 100) {
          throw new Error("Audio too small");
        }

        const blob = new Blob([bytes as BlobPart], {
          type: "audio/mpeg",
        });

        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);

        currentAudio = audio;
        currentObjectUrl = url;

        audio.onended = () => {
          stopAll();
          resolve();
        };

        audio.onerror = () => {
          stopAll();
          reject(new Error("Audio playback failed"));
        };

        audio.play().catch((error) => {
          stopAll();
          reject(error);
        });
      })
      .catch(reject);
  });
}

function speakBrowser(
  text: string,
  locale: string,
): Promise<void> {
  return new Promise((resolve) => {
    const synthesis = window.speechSynthesis;

    if (!synthesis) {
      resolve();
      return;
    }

    const langTags: Record<string, string> = {
      en: "en-IN",
      hi: "hi-IN",
      gu: "gu-IN",
      mr: "mr-IN",
      bn: "bn-IN",
    };

    const targetLang = langTags[locale] || locale;

    const doSpeak = () => {
      const utterance = new SpeechSynthesisUtterance(text);

      utterance.lang = targetLang;
      utterance.rate = 1;
      utterance.pitch = 1;

      const voices = synthesis.getVoices();

      const voice =
        voices.find((v) => v.lang === targetLang) ||
        voices.find((v) => v.lang.startsWith(locale)) ||
        voices.find((v) => v.lang.startsWith("en"));

      if (voice) {
        utterance.voice = voice;
        utterance.lang = voice.lang;
      }

      utterance.onend = () => resolve();
      utterance.onerror = () => resolve();

      synthesis.cancel();

      setTimeout(() => {
        synthesis.speak(utterance);
      }, 50);
    };

    if (synthesis.getVoices().length === 0) {
      const onLoaded = () => {
        synthesis.removeEventListener("voiceschanged", onLoaded);
        doSpeak();
      };

      synthesis.addEventListener("voiceschanged", onLoaded);
    } else {
      doSpeak();
    }
  });
}