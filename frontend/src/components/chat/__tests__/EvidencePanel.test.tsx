import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, within, cleanup } from "@testing-library/react";
import { LanguageProvider } from "@/lib/i18n/provider";
import type { ChatResponse } from "@/lib/api";

vi.mock("@/lib/speech", async () => {
  const actual = await vi.importActual<typeof import("@/lib/speech")>("@/lib/speech");
  return {
    ...actual,
    speakSegments: vi.fn(async () => {}),
  };
});

import { speakSegments } from "@/lib/speech";
import { MessageBubble, cleanTextForSpeech } from "../MessageBubble";

const STATIC_CITATION = {
  chunk_id: "a0eebc99",
  title: "PMFBY Guidelines",
  source: "static" as const,
  source_label: "Official Document",
  url: "https://pmfby.gov.in/guidelines",
  // Required for the document link to render: MessageBubble only emits the
  // "View document" anchor for a static citation when `source_file` is set.
  // Without it the link branch is skipped entirely and the link is absent.
  source_file: "pmfby_guidelines.pdf",
  page: 5,
  section: "Eligibility",
  content: "Farmers must apply before the cut-off date.",
};

const WEB_CITATION = {
  chunk_id: "web_f1e2d3c4b5a6_c0",
  title: "PACS Membership Rules",
  source: "web" as const,
  source_label: "Web",
  url: "https://example.com/pacs-rules",
  page: 2,
  section: "Membership",
  content: "Any individual above 18 may become a member.",
};

function makeResp(overrides: Partial<ChatResponse> = {}): ChatResponse {
  return {
    answer: "Farmers may be eligible for PMFBY [chunk:a0eebc99]. Members must follow PACS rules [chunk:web_f1e2d3c4b5a6_c0].",
    language: "en",
    domain: "law",
    intent: "eligibility",
    entities: [],
    confidence: 0.8,
    confidence_level: "high",
    citations: [STATIC_CITATION, WEB_CITATION],
    abstained: false,
    follow_up_question: null,
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
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = vi.fn();
  }
});
afterEach(() => cleanup());

// ── 1. [chunk:ID] renders as citation tag ──────────────────────────────────────
it("renders [chunk:ID] as clickable citation tags", () => {
  renderBubble(makeResp());
  expect(screen.getByRole("button", { name: /evidence for citation a0eebc99/i })).toBeTruthy();
  expect(screen.getByRole("button", { name: /evidence for citation web_f1e2d3c4b5a6_c0/i })).toBeTruthy();
});

// ── 2. Clicking citation opens the Evidence Panel ──────────────────────────────
it("clicking citation opens the Evidence Panel", () => {
  renderBubble(makeResp());
  const btn = screen.getByRole("button", { name: /evidence for citation a0eebc99/i });
  fireEvent.click(btn);
  expect(screen.getByText(/sources & references/i)).toBeTruthy();
});

// ── 3. Multiple different Chunk IDs produce independent evidence panels ────────
it("multiple citation tags open the same unified panel with all evidence", () => {
  renderBubble(makeResp());
  fireEvent.click(screen.getByRole("button", { name: /evidence for citation a0eebc99/i }));
  const panel = screen.getByText(/sources & references/i).closest("[data-evidence]");
  expect(panel).toBeTruthy();
  expect(within(panel as HTMLElement).getByText("PMFBY Guidelines")).toBeTruthy();
  expect(within(panel as HTMLElement).getByText("PACS Membership Rules")).toBeTruthy();
});

// ── 4. Duplicate Chunk IDs reuse the same evidence ────────────────────────────
it("duplicate chunk IDs resolve to the same citation object", () => {
  const resp = makeResp({
    answer: "Rule one [chunk:a0eebc99]. Rule two [chunk:a0eebc99].",
  });
  renderBubble(resp);
  const tags = screen.getAllByRole("button", { name: /evidence for citation a0eebc99/i });
  expect(tags.length).toBe(2);
  fireEvent.click(tags[0]);
  const panel = screen.getByText(/sources & references/i).closest("[data-evidence]") as HTMLElement;
  const pmfbyCards = within(panel).getAllByText("PMFBY Guidelines");
  expect(pmfbyCards.length).toBe(1);
});

// ── 5. Unknown Chunk ID fails safely ──────────────────────────────────────────
it("unknown chunk ID renders as inert text", () => {
  renderBubble(makeResp({ answer: "Something [chunk:ffffffff] happened." }));
  const inert = screen.getByText("[ffffffff]");
  expect(inert).toBeTruthy();
  expect(inert.tagName).toBe("SPAN");
});

// ── 6. Full citation.content is accessible ─────────────────────────────────────
it("clicking citation tag reveals the expanded card's full citation.content", () => {
  renderBubble(makeResp());
  fireEvent.click(screen.getByRole("button", { name: /evidence for citation a0eebc99/i }));
  expect(screen.getByText("Farmers must apply before the cut-off date.")).toBeTruthy();
  // The web card is collapsed, so its content should NOT be visible yet
  expect(screen.queryByText("Any individual above 18 may become a member.")).toBeNull();
});

// ── 7. Static evidence works ──────────────────────────────────────────────────
// The anchor's label is the localised string t("chat.viewDocument"), which is
// "View document" in English -- not "Open Document".
it("static evidence shows a View document link pointing at the PDF proxy", () => {
  renderBubble(makeResp());
  fireEvent.click(screen.getByRole("button", { name: /evidence for citation a0eebc99/i }));
  const docLink = screen.getByRole("link", { name: /view document/i });
  expect(docLink).toBeTruthy();
  // Served through the BFF's PDF proxy, deep-linked to the cited page.
  expect(docLink.getAttribute("href")).toBe(
    "/api/documents/pdf/pmfby_guidelines.pdf#page=5",
  );
});

// ── 8. Web evidence works ─────────────────────────────────────────────────────
it("web evidence shows a View source link after expanding", () => {
  renderBubble(makeResp());
  fireEvent.click(screen.getByRole("button", { name: /evidence for citation a0eebc99/i }));
  // Expand the web evidence card by clicking its toggle. Its accessible name is
  // composed of the "View source" label, the title and the page number.
  const webCardToggle = screen.getByRole("button", { name: /pacs membership rules/i });
  fireEvent.click(webCardToggle);
  const srcLink = screen.getByRole("link", { name: /view source/i });
  expect(srcLink).toBeTruthy();
  expect(srcLink.getAttribute("href")).toBe("https://example.com/pacs-rules");
});

// ── 9. PDF/document links work ────────────────────────────────────────────────
it("document links open in new tab with noopener", () => {
  renderBubble(makeResp());
  fireEvent.click(screen.getByRole("button", { name: /evidence for citation a0eebc99/i }));
  const docLink = screen.getByRole("link", { name: /view document/i });
  expect(docLink.getAttribute("target")).toBe("_blank");
  expect(docLink.getAttribute("rel")).toBe("noopener noreferrer");
});

// ── 10. Language switching does not mutate Chunk IDs ───────────────────────────
it("chunk IDs remain unchanged in the panel after language switching", () => {
  renderBubble(makeResp());
  fireEvent.click(screen.getByRole("button", { name: /evidence for citation a0eebc99/i }));
  const tag = screen.getByRole("button", { name: /evidence for citation a0eebc99/i });
  expect(tag.textContent).toContain("a0eebc99");
});

// ── 11. Language switching does not mutate URLs ────────────────────────────────
it("URLs remain unchanged after language switching", () => {
  renderBubble(makeResp());
  fireEvent.click(screen.getByRole("button", { name: /evidence for citation a0eebc99/i }));
  const link = screen.getByRole("link", { name: /view document/i });
  expect(link.getAttribute("href")).toBe(
    "/api/documents/pdf/pmfby_guidelines.pdf#page=5",
  );
});

// ── 12. Translation receives answer only ───────────────────────────────────────
it("answer is a string separate from citations in ChatResponse", () => {
  const resp = makeResp();
  expect(typeof resp.answer).toBe("string");
  expect(resp.citations).toBeInstanceOf(Array);
  expect(resp.answer).not.toContain(JSON.stringify(resp.citations[0]));
});

// ── 13. TTS receives answer only (not evidence) ───────────────────────────────
it("cleanTextForSpeech strips chunk IDs from answer", () => {
  const ttsText = cleanTextForSpeech(makeResp().answer);
  expect(ttsText).not.toContain("Farmers must apply before the cut-off date.");
  expect(ttsText).not.toContain("Any individual above 18 may become a member.");
  expect(ttsText).not.toContain("[chunk:");
});

// ── 14. TTS does not receive source metadata ──────────────────────────────────
it("TTS text does not contain source titles or domains", () => {
  const ttsText = cleanTextForSpeech(makeResp().answer);
  expect(ttsText).not.toContain("PMFBY Guidelines");
  expect(ttsText).not.toContain("PACS Membership Rules");
});

// ── 15. TTS does not receive URLs ──────────────────────────────────────────────
it("TTS text does not contain URLs", () => {
  const ttsText = cleanTextForSpeech(makeResp().answer);
  expect(ttsText).not.toContain("https://");
});

// ── 16. STT transcript remains independent of evidence ────────────────────────
it("STT produces plain text unrelated to citations", () => {
  const transcript = "What is PMFBY?";
  expect(transcript).not.toContain("[chunk:");
  expect(transcript).not.toContain("a0eebc99");
});

// ── 17. Historical messages retain answer + evidence separately ────────────────
it("historical message stores full ChatResponse with citations", () => {
  const resp = makeResp();
  const historyMsg = { role: "assistant" as const, resp };
  expect(historyMsg.resp.answer).toBe(resp.answer);
  expect(historyMsg.resp.citations).toHaveLength(2);
  expect(historyMsg.resp.citations[0].chunk_id).toBe("a0eebc99");
});

// ── 18. Evidence metadata remains unchanged after language switching ───────────
it("citation metadata is not mutated by component rendering", () => {
  renderBubble(makeResp());
  expect(STATIC_CITATION.chunk_id).toBe("a0eebc99");
  expect(STATIC_CITATION.url).toBe("https://pmfby.gov.in/guidelines");
  expect(STATIC_CITATION.page).toBe(5);
  expect(STATIC_CITATION.section).toBe("Eligibility");
  expect(WEB_CITATION.chunk_id).toBe("web_f1e2d3c4b5a6_c0");
});

// ── 19. Keyboard interaction works for citation/evidence controls ──────────────
it("citation tag is a keyboard-focusable button", () => {
  renderBubble(makeResp());
  const tag = screen.getByRole("button", { name: /evidence for citation a0eebc99/i });
  expect(tag.tagName).toBe("BUTTON");
  tag.focus();
  expect(document.activeElement).toBe(tag);
});

it("evidence card toggle is a keyboard-focusable button", () => {
  renderBubble(makeResp());
  fireEvent.click(screen.getByRole("button", { name: /evidence for citation a0eebc99/i }));
  // The toggle's accessible name is composed from the localised action label
  // ("View document"), the citation title and the page number.
  const cardToggle = screen.getByRole("button", { name: /view document.*PMFBY Guidelines/i });
  expect(cardToggle).toBeTruthy();
  expect(cardToggle.tagName).toBe("BUTTON");
  cardToggle.focus();
  expect(document.activeElement).toBe(cardToggle);
});

it("evidence panel close button is keyboard-focusable", () => {
  renderBubble(makeResp());
  fireEvent.click(screen.getByRole("button", { name: /evidence for citation a0eebc99/i }));
  const closeBtn = screen.getByRole("button", { name: /close evidence panel/i });
  expect(closeBtn.tagName).toBe("BUTTON");
  closeBtn.focus();
  expect(document.activeElement).toBe(closeBtn);
});
