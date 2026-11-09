import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { LanguageProvider } from "@/lib/i18n/provider";
import type { ChatResponse } from "@/lib/api";

// Mock only speakSegments; keep createSpeechService (used for stopSpeaking).
vi.mock("@/lib/speech", async () => {
  const actual = await vi.importActual<typeof import("@/lib/speech")>("@/lib/speech");
  return {
    ...actual,
    speakSegments: vi.fn(async () => {}),
  };
});

import { speakSegments } from "@/lib/speech";
import { MessageBubble } from "../MessageBubble";

function minimalResp(overrides: Partial<ChatResponse>): ChatResponse {
  return {
    answer: "You may be eligible for PMFBY if you are a farmer.",
    language: "en",
    domain: "law",
    intent: "eligibility",
    entities: [],
    confidence: 0.8,
    confidence_level: "high",
    citations: [],
    abstained: false,
    follow_up_question: null,
    speech_segments: undefined,
    ...overrides,
  };
}

function renderBubble(resp: ChatResponse) {
  return render(
    <LanguageProvider>
      <MessageBubble resp={resp} />
    </LanguageProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("MessageBubble read-aloud", () => {
  it("abstained response renders no read-aloud button", () => {
    renderBubble(
      minimalResp({ abstained: true, answer: "I cannot answer this with confidence.", speech_segments: undefined }),
    );

    // Abstention copy is present (en -> "This answer needs human verification").
    expect(screen.getByText(/needs human verification/i)).toBeTruthy();
    // No read-aloud control should exist in the abstained branch.
    expect(screen.queryByRole("button", { name: /read aloud/i })).toBeNull();
  });

  it("read-aloud button calls speakSegments with segments", async () => {
    const segments = [
      { text: "hello", language: "en" },
      { text: "नमस्ते", language: "hi" },
    ];
    renderBubble(minimalResp({ speech_segments: segments }));

    const btn = screen.getByRole("button", { name: /read aloud/i });
    expect(btn).toBeTruthy();

    fireEvent.click(btn);

    await waitFor(() => {
      expect(speakSegments).toHaveBeenCalledWith(segments);
    });
  });

  it("read-aloud button always renders even when segments are empty", () => {
    renderBubble(minimalResp({ speech_segments: [] }));
    expect(screen.getByRole("button", { name: /read aloud/i })).toBeTruthy();
  });
});
