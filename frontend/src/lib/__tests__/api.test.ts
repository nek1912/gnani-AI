import { test, expect, vi, afterEach } from "vitest";
import { sendChat, fetchVoiceSpeak, fetchVoiceTranscribe, type SpeechSegment } from "../api";
import { backendPath, backendUrl } from "../backend";

type FetchMock = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<{ ok: boolean; json: () => Promise<unknown> }>;

afterEach(() => {
  vi.unstubAllGlobals();
});

/*
 * The Express BFF was removed, so requests now go straight to the FastAPI
 * backend. These assertions pin that mapping: the callers still pass the old
 * `/api/*` paths, and backend.ts rewrites them to FastAPI's routes and prefixes
 * the backend origin.
 */
test("backendPath maps BFF paths onto FastAPI routes", () => {
  // /api/chat is the non-streaming JSON route; only /api/chat/stream is SSE.
  expect(backendPath("/api/chat")).toBe("/chat");
  expect(backendPath("/api/chat/stream")).toBe("/chat/stream");
  expect(backendPath("/api/grievance/detect")).toBe("/grievances");
  expect(backendPath("/api/grievance/answer")).toBe("/grievances/answer");
  expect(backendPath("/api/grievance/clarify")).toBe("/grievances/clarify");
  expect(backendPath("/api/grievance/finalize")).toBe("/grievances/finalize");
  expect(backendPath("/api/speak")).toBe("/voice/speak");
  expect(backendPath("/api/voice/speak")).toBe("/voice/speak");
  expect(backendPath("/api/voice/transcribe")).toBe("/voice/transcribe");
  expect(backendPath("/api/translate")).toBe("/translate");
});

test("backendPath converts the grievance fields query into a path parameter", () => {
  expect(backendPath("/api/grievance/fields?conversation_id=abc&language=hi")).toBe(
    "/grievances/abc/fields?language=hi",
  );
  // Default language omitted entirely when not supplied.
  expect(backendPath("/api/grievance/fields?conversation_id=abc")).toBe(
    "/grievances/abc/fields",
  );
});

test("backendUrl prefixes the configured backend origin", () => {
  expect(backendUrl("/api/translate")).toBe("http://localhost:8000/translate");
});

test("fetchVoiceSpeak posts segments to the backend and returns audio hex", async () => {
  const segments: SpeechSegment[] = [{ text: "hello", language: "en" }];
  const fetchMock = vi.fn<FetchMock>(async () => ({
    ok: true,
    json: async () => ({ audio: "48656c6c6f", language: "en" }),
  }));
  vi.stubGlobal("fetch", fetchMock);

  const result = await fetchVoiceSpeak(segments);

  expect(fetchMock).toHaveBeenCalledTimes(1);
  const call = fetchMock.mock.calls[0];
  const [url, init] = call as [RequestInfo | URL, RequestInit];
  expect(url).toBe("http://localhost:8000/voice/speak");
  expect(init.method).toBe("POST");
  const body = JSON.parse(init.body as string);
  expect(body.segments).toEqual(segments);
  expect(result).toEqual({ audio: "48656c6c6f", language: "en" });
});

test("fetchVoiceTranscribe posts audio base64 to backend and returns transcript", async () => {
  const fetchMock = vi.fn<FetchMock>(async () => ({
    ok: true,
    json: async () => ({ text: "नमस्ते किसान", language: "hi" }),
  }));
  vi.stubGlobal("fetch", fetchMock);

  const result = await fetchVoiceTranscribe("fakebase64audio==", "hi");

  expect(fetchMock).toHaveBeenCalledTimes(1);
  const call = fetchMock.mock.calls[0];
  const [url, init] = call as [RequestInfo | URL, RequestInit];
  expect(url).toBe("http://localhost:8000/voice/transcribe");
  expect(init.method).toBe("POST");
  const body = JSON.parse(init.body as string);
  expect(body.audio).toBe("fakebase64audio==");
  expect(body.language).toBe("hi");
  expect(result).toEqual({ text: "नमस्ते किसान", language: "hi" });
});

test("sendChat serializes ui_language_explicit when provided", async () => {
  const fetchMock = vi.fn<FetchMock>(async () => ({
    ok: true,
    json: async () => ({
      answer: "a",
      language: "hi",
      domain: "d",
      intent: "i",
      entities: [],
      confidence: 0.5,
      confidence_level: "moderate",
      citations: [],
      abstained: false,
      follow_up_question: null,
    }),
  }));
  vi.stubGlobal("fetch", fetchMock);

  await sendChat({
    question: "q",
    session_id: "s",
    language: "hi",
    state: null,
    ui_language_explicit: true,
  });

  const call = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
  const body = JSON.parse(call[1].body as string);
  expect(body.ui_language_explicit).toBe(true);

  fetchMock.mockClear();
  await sendChat({
    question: "q",
    session_id: "s",
    language: "hi",
    state: null,
  });
  const call2 = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
  const body2 = JSON.parse(call2[1].body as string);
  expect(body2.ui_language_explicit).toBeUndefined();
});
