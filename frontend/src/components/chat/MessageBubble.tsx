import { useState, useMemo, useRef, useEffect } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link } from "react-router-dom";
import type { ChatResponse } from "@/lib/api";
import { useI18n } from "@/lib/i18n/provider";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import {
  IconSpeaker,
  IconDoc,
  IconGlobe,
  IconChevronRight,
  IconCopy,
  IconCheck,
  IconThumbsUp,
  IconThumbsDown,
  IconBot,
} from "@/components/ui/Icons";
import { deco } from "@/lib/data/deco";
import { createSpeechService, speakSegments } from "@/lib/speech";
import { EvidenceBand } from "@/components/EvidenceBand";
import { evidenceBand } from "@/lib/band";
import styles from "./MessageBubble.module.css";

type Citation = ChatResponse["citations"][number];

const CHUNK_TAG_RE = /\[chunk:([^\]]+)\]/gi;

function parseAnswerSegments(
  answer: string,
): Array<{ type: "text"; value: string } | { type: "cite"; id: string; raw: string }> {
  const segments: Array<{ type: "text"; value: string } | { type: "cite"; id: string; raw: string }> = [];
  let lastIndex = 0;
  for (const m of answer.matchAll(CHUNK_TAG_RE)) {
    if (m.index! > lastIndex) {
      segments.push({ type: "text", value: answer.slice(lastIndex, m.index) });
    }
    segments.push({ type: "cite", id: m[1].toLowerCase(), raw: m[0] });
    lastIndex = m.index! + m[0].length;
  }
  if (lastIndex < answer.length) {
    segments.push({ type: "text", value: answer.slice(lastIndex) });
  }
  return segments;
}

function buildCitationMap(citations: Citation[]): Map<string, Citation> {
  const map = new Map<string, Citation>();
  for (const c of citations) {
    if (c.chunk_id) map.set(c.chunk_id.toLowerCase(), c);
  }
  return map;
}

function resolveCitation(
  id: string,
  citationMap: Map<string, Citation>,
): Citation | undefined {
  const exact = citationMap.get(id);
  if (exact) return exact;
  for (const [key, cit] of citationMap) {
    if (key.startsWith(id) || id.startsWith(key)) return cit;
  }
  return undefined;
}

function EvidenceCard({
  citation,
  isHighlighted,
  isExpanded,
  onToggle,
}: {
  citation: Citation;
  isHighlighted: boolean;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const isWeb = citation.source === "web";
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isHighlighted && cardRef.current) {
      cardRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [isHighlighted]);

  return (
    <div
      ref={cardRef}
      id={citation.chunk_id ? `evidence-${citation.chunk_id}` : undefined}
      className={`rounded-[var(--radius-md)] border transition-all duration-200 ${
        isHighlighted
          ? "border-[var(--accent-legal)] bg-[var(--surface-elevated)] shadow-[var(--shadow-sm)]"
          : "border-[var(--border-soft)] bg-[var(--canvas)]"
      }`}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isExpanded}
        className="flex w-full items-start gap-3 p-3 text-left"
      >
        <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded ${
          isWeb ? "bg-blue-100 text-blue-600" : "bg-amber-100 text-amber-700"
        }`}>
          {isWeb ? <IconGlobe className="h-3.5 w-3.5" /> : <IconDoc className="h-3.5 w-3.5" />}
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-faint)]">
            {isWeb ? t("chat.viewSource") : t("chat.viewDocument")}
          </p>
          <p className="text-sm font-semibold leading-snug text-[var(--ink)] line-clamp-2">
            {citation.title}
          </p>
          {(citation.page || citation.section) && (
            <p className="text-xs text-[var(--text-tertiary)]">
              {citation.page && <span>Page {citation.page}</span>}
              {citation.page && citation.section && <span className="mx-1.5">&middot;</span>}
              {citation.section && <span>Section {citation.section}</span>}
            </p>
          )}
        </div>
        <IconChevronRight
          className={`mt-1 h-4 w-4 shrink-0 text-[var(--text-faint)] transition-transform duration-200 ${
            isExpanded ? "rotate-90" : ""
          }`}
        />
      </button>
      {isExpanded && (
        <div className="px-3 pb-3 space-y-2.5">
          {citation.content && (
            <div className="rounded-[var(--radius-sm)] border border-[var(--border-soft)] bg-[var(--cream)] p-3 text-xs leading-relaxed text-[var(--ink)] whitespace-pre-wrap max-h-64 overflow-y-auto">
              {citation.content}
            </div>
          )}
          <div className="flex items-center gap-3">
            {isWeb && citation.url && (
              <a
                href={citation.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--accent-legal)] transition-colors hover:text-[var(--accent-primary)]"
              >
                {t("chat.viewSource")}
                <span className="text-[10px]">&#8599;</span>
              </a>
            )}
            {!isWeb && citation.source_file && (
              <a
                href={`/api/documents/pdf/${encodeURIComponent(citation.source_file)}${citation.page ? `#page=${citation.page}` : ""}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--accent-legal)] transition-colors hover:text-[var(--accent-primary)]"
              >
                {t("chat.viewDocument")}
                <span className="text-[10px]">&#8599;</span>
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function EvidencePanel({
  citations,
  expandedChunkId,
  onToggleChunk,
  onClose,
}: {
  citations: Citation[];
  expandedChunkId: string | null;
  onToggleChunk: (chunkId: string) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <div
      data-evidence="true"
      className="mt-3 rounded-[var(--radius-md)] border border-[var(--border-soft)] bg-[var(--surface-elevated)] overflow-hidden"
    >
      <div className="flex items-center justify-between border-b border-[var(--border-soft)] bg-[var(--cream)] px-4 py-2.5">
        <div className="flex items-center gap-2">
          <IconDoc className="h-4 w-4 text-[var(--accent-legal)]" />
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
            {t("chat.sourcesReferences")}
          </p>
          <span className="rounded-full bg-[var(--accent-legal)]/10 px-2 py-0.5 text-[10px] font-bold text-[var(--accent-legal)]">
            {citations.length}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-[var(--text-tertiary)] hover:text-[var(--ink)] text-xs transition-colors rounded-[var(--radius-sm)] px-1.5 py-0.5 hover:bg-[var(--cream-2)]"
          aria-label="Close evidence panel"
        >
          &#10005;
        </button>
      </div>
      <div className="p-2.5 space-y-2">
        {citations.map((c, i) => (
          <EvidenceCard
            key={c.chunk_id || i}
            citation={c}
            isHighlighted={expandedChunkId === c.chunk_id}
            isExpanded={expandedChunkId === c.chunk_id}
            onToggle={() => onToggleChunk(c.chunk_id || `idx-${i}`)}
          />
        ))}
      </div>
    </div>
  );
}

function CitationTag({
  id,
  citationMap,
  isExpanded,
  onToggle,
}: {
  id: string;
  citationMap: Map<string, Citation>;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const citation = resolveCitation(id, citationMap);
  if (!citation) {
    return (
      <span
        className="inline-flex items-center rounded bg-[var(--cream)] px-1 py-0.5 text-[10px] font-mono text-[var(--text-faint)] border border-[var(--border-soft)]"
        aria-label={`Unknown citation: ${id}`}
      >
        [{id}]
      </span>
    );
  }

  return (
    <span className="relative inline-block">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isExpanded}
        aria-label={`Evidence for citation ${id}`}
        className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-bold transition-all ${
          citation.source === "web"
            ? "bg-blue-50 text-blue-600 hover:bg-blue-100"
            : "bg-amber-50 text-amber-700 hover:bg-amber-100"
        } ${isExpanded ? "ring-1 ring-current shadow-[var(--shadow-sm)]" : ""}`}
      >
        {citation.source === "web" ? <IconGlobe className="h-2.5 w-2.5" /> : <IconDoc className="h-2.5 w-2.5" />}
        {id}
      </button>
    </span>
  );
}

export function cleanMarkdownForDisplay(text: string): string {
  if (!text) return "";
  let cleaned = text;

  // Remove internal chunk citation tags (e.g. [chunk:123], (chunk:123))
  cleaned = cleaned.replace(/\[chunk:[^\]]*\]/gi, "");
  cleaned = cleaned.replace(/\(chunk:[^\)]*\)/gi, "");

  // Clean empty format strings leftover from citation removal (e.g. ***, * *, ())
  cleaned = cleaned.replace(/\*\s*\*/g, "");
  cleaned = cleaned.replace(/\(\s*\)/g, "");

  // Fix unclosed/orphaned single asterisks attached to words before cell boundaries or newlines
  // Use Unicode-aware word boundary: match any script word characters (not just ASCII \w)
  cleaned = cleaned.replace(/([\p{L}\p{N}]+)\*\s*(?=[\|\]\)\n])/gu, "$1");

  // Fix escaped asterisks (\*\* -> **)
  cleaned = cleaned.replace(/\\\*/g, "*");

  // Format bullet points: replace inline bullets (•) with newlines and markdown dash (- )
  // The bullet character • (U+2022) is used across many languages including Indian scripts
  cleaned = cleaned.replace(/([^\n])\s*•\s*/g, "$1\n- ");
  cleaned = cleaned.replace(/^\s*•\s*/gm, "- ");

  // Ensure numbered list items on inline text get proper linebreaks
  // Match any digit (including those in non-Latin scripts that use Arabic numerals)
  cleaned = cleaned.replace(/([^\n])\s*(\d+\.)\s+/g, "$1\n$2 ");

  // Preserve double newlines for paragraph breaks, remove excess newlines
  cleaned = cleaned.replace(/\n{3,}/g, "\n\n");

  return cleaned.trim();
}

export function cleanTextForSpeech(text: string): string {
  if (!text) return "";
  let cleaned = text;

  // Remove chunk citations
  cleaned = cleaned.replace(/\[chunk:[^\]]*\]/gi, "");
  cleaned = cleaned.replace(/\(chunk:[^\)]*\)/gi, "");

  // Remove markdown headers
  cleaned = cleaned.replace(/^#+\s+/gm, "");

  // Convert bullet points to sentence endings
  cleaned = cleaned.replace(/^[\s]*[-*+•]\s+/gm, ". ");
  cleaned = cleaned.replace(/([^\n])\s*•\s*/g, "$1. ");

  // Strip markdown formatting symbols
  cleaned = cleaned.replace(/\*\*([^*]+)\*\*/g, "$1");
  cleaned = cleaned.replace(/\*([^*]+)\*/g, "$1");
  cleaned = cleaned.replace(/`([^`]+)`/g, "$1");
  cleaned = cleaned.replace(/\\\*/g, "");

  // Replace newlines with sentence breaks
  cleaned = cleaned.replace(/\n+/g, ". ");

  // Normalize duplicate spaces and periods
  cleaned = cleaned.replace(/\.\s*\./g, ".");
  cleaned = cleaned.replace(/\s+/g, " ").trim();

  return cleaned;
}

export function MessageBubble({ resp, isStreaming = false }: { resp: ChatResponse; isStreaming?: boolean }) {
  const { t } = useI18n();
  const speech = useMemo(() => createSpeechService(), []);
  const [speaking, setSpeaking] = useState(false);
  const [copied, setCopied] = useState(false);
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [expandedChunkId, setExpandedChunkId] = useState<string | null>(null);
  const [evidencePanelOpen, setEvidencePanelOpen] = useState(false);

  const segments = resp.speech_segments ?? [];
  const hasSegments = segments.length > 0;
  const domainKey = `domain.${resp.domain}`;
  const domainLabel = t(domainKey).startsWith("domain.") ? resp.domain : t(domainKey);

  const citationMap = useMemo(() => buildCitationMap(resp.citations), [resp.citations]);
  const answerSegments = useMemo(() => parseAnswerSegments(resp.answer), [resp.answer]);

  async function handleSpeak() {
    if (speaking) {
      speech.stopSpeaking();
      setSpeaking(false);
      return;
    }
    setSpeaking(true);
    try {
      if (hasSegments) {
        await speakSegments(segments);
      } else {
        const cleanText = cleanTextForSpeech(resp.answer);
        await speech.speak(cleanText, resp.language);
      }
    } finally {
      setSpeaking(false);
    }
  }

  function handleCopy() {
    const cleanText = cleanMarkdownForDisplay(resp.answer);
    navigator.clipboard.writeText(cleanText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (resp.abstained) {
    return (
      <div className="group flex gap-3 text-sm sm:text-base leading-relaxed text-[var(--ink)]">
        <div className="min-w-0 flex-1 space-y-2">
          <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge deco={deco(resp.domain)}>{domainLabel}</Badge>
            </div>
          </div>
          <Alert tone={resp.transport_error ? "error" : "warn"}>
            {resp.transport_error ? (
              <p>{t("common.error")}</p>
            ) : (
              <div className="space-y-1">
                <p className="font-semibold">{t("abstained.title")}</p>
                <p className="text-xs opacity-80">{t("abstained.description")}</p>
              </div>
            )}
          </Alert>
        </div>
      </div>
    );
  }

  return (
    <div className="group flex gap-3 text-sm sm:text-base leading-relaxed text-[var(--ink)]">
      <div className="min-w-0 flex-1 space-y-2">
        <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge deco={deco(resp.domain)}>{domainLabel}</Badge>
            {resp.mode && (
              <span
                className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] sm:text-xs font-medium ${
                  resp.mode === "web"
                    ? "bg-blue-100 text-blue-800"
                    : resp.mode === "grievance"
                      ? "bg-orange-100 text-orange-800"
                      : "bg-gray-100 text-gray-600"
                }`}
              >
                {resp.mode === "web" ? t("chat.mode.webSearch") : resp.mode === "grievance" ? t("chat.mode.grievance") : t("chat.mode.staticRag")}
              </span>
            )}
            <EvidenceBand confidence={resp.confidence} label={t(`evidence.${evidenceBand(resp.confidence)}`)} />
          </div>
          <span className="text-[11px] sm:text-xs text-[var(--muted-soft)]">{(resp.confidence * 100).toFixed(0)}% match</span>
        </div>

        {/* Answer Content */}
        <div className={`font-answer text-sm sm:text-base leading-relaxed text-[var(--ink)] prose prose-sm max-w-none prose-headings:font-semibold prose-headings:text-[var(--ink)] prose-p:my-2 prose-p:leading-relaxed prose-ul:my-2.5 prose-ul:list-disc prose-ul:pl-5 prose-ol:my-2.5 prose-ol:list-decimal prose-ol:pl-5 prose-li:my-1 prose-strong:font-semibold prose-strong:text-[var(--ink)] prose-table:text-xs prose-th:font-semibold prose-td:py-1 prose-th:py-1 prose-pre:bg-[var(--primary)] prose-pre:text-[var(--on-primary)] prose-code:text-[var(--ink)] ${isStreaming ? styles.streamingText : ""}`}>
          {answerSegments.map((seg, i) => {
            if (seg.type === "text") {
              return (
                <Markdown
                  key={i}
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p: ({ children }) => <p className="mb-2.5 leading-relaxed text-[var(--ink)]">{children}</p>,
                    ul: ({ children }) => <ul className="my-2.5 list-disc pl-5 space-y-1 text-[var(--ink)]">{children}</ul>,
                    ol: ({ children }) => <ol className="my-2.5 list-decimal pl-5 space-y-1 text-[var(--ink)]">{children}</ol>,
                    li: ({ children }) => <li className="pl-1 leading-relaxed">{children}</li>,
                    strong: ({ children }) => <strong className="font-semibold text-[var(--ink)]">{children}</strong>,
                    h1: ({ children }) => <h1 className="text-lg font-bold my-2 text-[var(--ink)]">{children}</h1>,
                    h2: ({ children }) => <h2 className="mt-5 mb-2 border-b border-[var(--border-soft)] pb-1.5 text-base font-bold text-[var(--ink)]">{children}</h2>,
                    h3: ({ children }) => <h3 className="mt-4 mb-1.5 text-sm font-semibold text-[var(--accent-legal)]">{children}</h3>,
                    blockquote: ({ children }) => <blockquote className="my-3 border-l-2 border-[var(--accent-legal)]/40 pl-3 italic text-[var(--text-tertiary)]">{children}</blockquote>,
                    table: ({ children }) => <div className="not-prose my-4 overflow-hidden rounded-[var(--radius-md)] border border-[var(--border-soft)] bg-[var(--canvas)] shadow-xs"><div className="overflow-x-auto"><table className="w-full min-w-[500px] border-collapse border-spacing-0 text-left text-xs sm:text-sm">{children}</table></div></div>,
                    thead: ({ children }) => <thead className="bg-[var(--cream)] text-[var(--ink)] border-b-2 border-[var(--border-soft)]">{children}</thead>,
                    th: ({ children }) => <th className="border-r border-[var(--border-soft)] last:border-r-0 border-b-2 border-b-[var(--border-soft)] px-4 py-3 font-bold text-[var(--ink)] bg-[var(--cream)] text-left align-middle">{children}</th>,
                    tr: ({ children }) => <tr className="border-b border-[var(--border-soft)] last:border-b-0 hover:bg-[var(--surface-elevated)]/50 transition-colors bg-[var(--canvas)]">{children}</tr>,
                    td: ({ children }) => <td className="border-r border-[var(--border-soft)] last:border-r-0 px-4 py-3 align-top leading-relaxed text-[var(--ink)] bg-[var(--canvas)]">{children}</td>,
                    hr: () => <hr className="my-4 border-[var(--border-soft)]" />,
                    a: ({ children, href }) => <a href={href} className="font-medium text-[var(--accent-legal)] underline decoration-[var(--accent-legal)]/30 underline-offset-2 hover:decoration-current" target="_blank" rel="noreferrer">{children}</a>,
                  }}
                >
                  {cleanMarkdownForDisplay(seg.value)}
                </Markdown>
              );
            }
            return (
              <span key={i} className="inline-block align-middle mx-0.5">
                <CitationTag
                  id={seg.id}
                  citationMap={citationMap}
                  isExpanded={expandedChunkId === seg.id}
                  onToggle={() => {
                    setEvidencePanelOpen(true);
                    setExpandedChunkId((prev) => (prev === seg.id ? null : seg.id));
                  }}
                />
              </span>
            );
          })}
        </div>

        {resp.citations.length > 0 && !evidencePanelOpen && (
          <div className="flex items-center gap-2 py-1">
            <span className="flex h-4 w-4 items-center justify-center rounded-full bg-[var(--accent-legal)]/10">
              <svg className="h-2.5 w-2.5 text-[var(--accent-legal)]" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M2 6l3 3 5-5" />
              </svg>
            </span>
            <span className="text-xs font-medium text-[var(--accent-legal)]">
              {t("chat.grounded")}
            </span>
          </div>
        )}

        {evidencePanelOpen && resp.citations.length > 0 && (
          <EvidencePanel
            citations={resp.citations}
            expandedChunkId={expandedChunkId}
            onToggleChunk={(chunkId) =>
              setExpandedChunkId((prev) => (prev === chunkId ? null : chunkId))
            }
            onClose={() => {
              setEvidencePanelOpen(false);
              setExpandedChunkId(null);
            }}
          />
        )}

        {resp.domain === "schemes" && (
          <div className="mt-3">
            <Link to="/schemes">
              <button
                type="button"
                className="inline-flex items-center gap-1.5 rounded-[var(--radius-cta)] border border-[var(--ink)]/40 bg-[var(--surface-soft)] px-3 py-1.5 text-xs font-semibold text-[var(--ink)] transition-colors hover:border-[var(--ink)] hover:bg-[var(--surface-card)]"
              >
                {t("chat.exploreSchemes")}
                <IconChevronRight className="h-3.5 w-3.5 text-[var(--ink)]" />
              </button>
            </Link>
          </div>
        )}

        {/* Actions Footer */}
        {!isStreaming && (
          <div className="pt-2 flex flex-wrap items-center gap-1.5 text-xs text-[var(--muted-soft)]">
            {/* Copy Button */}
            <button
              type="button"
              onClick={handleCopy}
              title={copied ? t("chat.copied") : t("chat.copyResponse")}
              className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] text-[var(--muted)] transition-colors hover:bg-[var(--surface-card)] hover:text-[var(--ink)]"
            >
              {copied ? <IconCheck className="h-3.5 w-3.5 text-[var(--state-success)]" /> : <IconCopy className="h-3.5 w-3.5" />}
            </button>

            {/* Read Aloud Button */}
            <button
              type="button"
              onClick={handleSpeak}
              title={speaking ? t("common.stopReadAloud") : t("common.readAloud")}
              className={`flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] transition-colors hover:bg-[var(--surface-card)] hover:text-[var(--ink)] ${
                speaking ? "text-[var(--ink)] bg-[var(--accent-tint-soft)]" : "text-[var(--muted)]"
              }`}
            >
              <IconSpeaker className={`h-3.5 w-3.5 ${speaking ? "animate-pulse" : ""}`} />
            </button>

            {/* Thumbs Up Button */}
            <button
              type="button"
              onClick={() => setRating((r) => (r === "up" ? null : "up"))}
              title={t("chat.goodResponse")}
              className={`flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] transition-colors hover:bg-[var(--surface-card)] hover:text-[var(--ink)] ${
                rating === "up" ? "text-[var(--state-success)] bg-[var(--surface-card)]" : "text-[var(--muted)]"
              }`}
            >
              <IconThumbsUp className="h-3.5 w-3.5" />
            </button>

            {/* Thumbs Down Button */}
            <button
              type="button"
              onClick={() => setRating((r) => (r === "down" ? null : "down"))}
              title={t("chat.badResponse")}
              className={`flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] transition-colors hover:bg-[var(--surface-card)] hover:text-[var(--ink)] ${
                rating === "down" ? "text-[var(--state-error)] bg-[var(--surface-card)]" : "text-[var(--muted)]"
              }`}
            >
              <IconThumbsDown className="h-3.5 w-3.5" />
            </button>

            {/* Citations Trigger Button */}
            {resp.citations.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  setEvidencePanelOpen((o) => !o);
                  setExpandedChunkId(null);
                }}
                aria-expanded={evidencePanelOpen}
                className={`ml-auto inline-flex items-center gap-1.5 rounded-[var(--radius-md)] border px-2.5 py-1.5 text-xs font-semibold transition-all ${
                  evidencePanelOpen
                    ? "border-[var(--accent-legal)]/30 bg-[var(--accent-legal)]/5 text-[var(--accent-legal)]"
                    : "border-[var(--border-soft)] bg-[var(--cream)] text-[var(--text-body)] hover:border-[var(--accent-legal)]/30 hover:text-[var(--accent-legal)]"
                }`}
              >
                <IconDoc className="h-3.5 w-3.5" />
                <span>{resp.citations.length} {t("common.source")}</span>
                <IconChevronRight className={`h-3 w-3 transition-transform duration-200 ${evidencePanelOpen ? "rotate-90" : ""}`} />
              </button>
            )}
          </div>
        )}

        {/* Evidence Panel replaces the legacy sources list */}
      </div>
    </div>
  );
}

