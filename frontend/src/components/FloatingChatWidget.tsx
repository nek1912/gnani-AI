import { useState, useRef, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { sendChatStream, type StreamEvent } from "@/lib/api";
import { useI18n } from "@/lib/i18n/provider";
import type { Locale } from "@/lib/i18n/i18n";
import { createSpeechService } from "@/lib/speech";
import { IconMic, IconSend, IconX, IconBot } from "@/components/ui/Icons";
import { cleanMarkdownForDisplay } from "@/components/chat/MessageBubble";

type Msg = { role: "user" | "assistant"; text?: string };

export function FloatingChatWidget() {
  const { t, locale } = useI18n();
  const lang: Locale = locale;
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [typing, setTyping] = useState(false);
  const [listening, setListening] = useState(false);
  const speech = useState(() => createSpeechService())[0];
  const cancelListen = useRef<(() => void) | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [sessionId] = useState(() => crypto.randomUUID());
  const [displayedAnswer, setDisplayedAnswer] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const tokenBufferRef = useRef("");
  const isNearBottomRef = useRef(true);

  const checkIfNearBottom = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const { scrollTop, scrollHeight, clientHeight } = container;
    isNearBottomRef.current = scrollHeight - scrollTop - clientHeight < 150;
  }, []);

  const scrollToBottom = useCallback(() => {
    setTimeout(() => {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 50);
  }, []);

  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
      return () => { document.body.style.overflow = ""; };
    }
  }, [open]);

  // Attach scroll listener
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.addEventListener("scroll", checkIfNearBottom, { passive: true });
    checkIfNearBottom();
    return () => container.removeEventListener("scroll", checkIfNearBottom);
  }, [checkIfNearBottom, open]);

  // Only auto-scroll when new content arrives if user is near bottom
  useEffect(() => {
    if (isNearBottomRef.current) {
      scrollToBottom();
    }
  }, [displayedAnswer, scrollToBottom]);

  const ask = useCallback(async (q?: string) => {
    const question = (q ?? input).trim();
    if (!question || typing) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", text: question }]);
    setTyping(true);
    setDisplayedAnswer("");
    tokenBufferRef.current = "";
    // Scroll to show the user's question
    isNearBottomRef.current = true;
    scrollToBottom();

    const abortController = new AbortController();
    abortRef.current = abortController;

    try {
      await sendChatStream(
        {
          question,
          session_id: sessionId,
          language: lang,
          state: null,
          history: [],
          ui_language_explicit: false,
        },
        (event: StreamEvent) => {
          if (event.event === "token") {
            const text = (event.data.text as string).replace(/INSUFFICIENT_EVIDENCE/g, "");
            if (text) {
              tokenBufferRef.current += text;
              setDisplayedAnswer(tokenBufferRef.current);
            }
          }
        },
        abortController.signal,
      );

      const finalAnswer = tokenBufferRef.current;
      setMsgs((m) => [...m, { role: "assistant", text: finalAnswer }]);
      setDisplayedAnswer("");
    } catch (err) {
      console.error("Chat error:", err);
      if (err instanceof Error && err.name === "AbortError") return;
      setMsgs((m) => [...m, { role: "assistant", text: t("chat.widget.error") }]);
      setDisplayedAnswer("");
    } finally {
      setTyping(false);
      tokenBufferRef.current = "";
      abortRef.current = null;
    }
  }, [input, typing, lang, sessionId, scrollToBottom]);

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      ask();
    }
  }

  function toggleMic() {
    if (listening) {
      cancelListen.current?.();
      setListening(false);
      return;
    }
    cancelListen.current = speech.listen(lang, (text) => {
      setInput((prev) => (prev ? prev + " " : "") + text);
      setListening(false);
    });
    setListening(true);
  }

  const starters = [
    t("chat.starter1"),
    t("chat.starter2"),
    t("chat.starter3"),
  ];

  return (
    <>
      {!open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="fixed bottom-4 right-4 z-50 group cursor-pointer sm:bottom-6 sm:right-6"
          aria-label="Open chat"
        >
          <div className="relative bg-black/90 p-4 rounded-full">
            <img
              src="/virtual-assistant.png"
              alt="JanSahay Assistant"
              className="h-15 w-15 shadow-[0_8px_32px_rgba(0,0,0,0.15)] object-cover transition-transform duration-300 group-hover:scale-105"
            />
          </div>
        </button>
      )}

      {open && (
        <div
          className="fixed bottom-3 inset-x-3 sm:inset-auto sm:bottom-6 sm:right-6 z-50 flex max-w-[380px] sm:w-[380px] mx-auto flex-col overflow-hidden rounded-[var(--radius-xl)] border border-[var(--hairline)] bg-[var(--canvas)] shadow-[0_16px_64px_rgba(0,0,0,0.18)]"
          style={{ height: "min(580px, calc(100vh - 80px))" }}
          onWheel={(e) => e.stopPropagation()}
          onTouchMove={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center gap-3 border-b border-[var(--hairline)] bg-[var(--surface-soft)] px-4 py-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--on-primary)]">
              <IconBot className="h-5 w-5" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-[var(--ink)]">JanSahay</p>
              <p className="text-[11px] text-[var(--muted)]">{t("chat.widget.subtitle")}</p>
            </div>
            <div className="flex items-center gap-1">
              <Link
                to="/chat"
                className="rounded-full bg-[var(--primary)] px-3 py-1 text-[11px] font-semibold text-[var(--on-primary)] transition-colors hover:bg-[#1a1a1a]"
              >
                {t("chat.widget.openFull")}
              </Link>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="flex h-8 w-8 items-center justify-center rounded-full text-[var(--muted)] transition-colors hover:bg-[var(--cream)] hover:text-[var(--ink)]"
                aria-label="Close chat"
              >
                <IconX className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Messages */}
          <div ref={scrollContainerRef} className="flex-1 min-h-0 overflow-y-auto px-4 py-4 space-y-4 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
            {msgs.length === 0 && !typing && (
              <div className="space-y-4">
                <div className="flex gap-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--on-primary)]">
                    <IconBot className="h-4 w-4" />
                  </div>
                  <div className="max-w-[80%] rounded-[var(--radius-lg)] bg-[var(--surface-soft)] px-4 py-3 text-[13px] leading-relaxed text-[var(--ink)]">
                    <span dangerouslySetInnerHTML={{ __html: t("chat.widget.greeting") }} />
                  </div>
                </div>
                <div className="space-y-2 pl-11">
                  {starters.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => { setInput(s); inputRef.current?.focus(); }}
                      className="block w-full rounded-[var(--radius-md)] border border-[var(--hairline)] bg-white px-3 py-2 text-left text-[12px] text-[var(--body)] transition-colors hover:border-[var(--ink)]/30 hover:bg-[var(--cream)]"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {msgs.map((m, i) =>
              m.role === "user" ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[80%] rounded-[var(--radius-lg)] bg-[var(--primary)] px-4 py-2.5 text-[13px] leading-relaxed text-[var(--on-primary)]">
                    {m.text}
                  </div>
                </div>
              ) : (
                <div key={i} className="flex gap-3">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--on-primary)]">
                    <IconBot className="h-3.5 w-3.5" />
                  </div>
                  <div className="max-w-[80%] rounded-[var(--radius-lg)] bg-[var(--surface-soft)] px-4 py-2.5 text-[13px] leading-relaxed text-[var(--ink)]">
                    <Markdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                        ul: ({ children }) => <ul className="my-2 list-disc pl-5 space-y-1">{children}</ul>,
                        ol: ({ children }) => <ol className="my-2 list-decimal pl-5 space-y-1">{children}</ol>,
                        li: ({ children }) => <li className="pl-1">{children}</li>,
                        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                      }}
                    >
                      {cleanMarkdownForDisplay(m.text || "")}
                    </Markdown>
                  </div>
                </div>
              )
            )}



            {typing && !displayedAnswer && (
              <div className="flex gap-3 animate-in fade-in duration-200">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--on-primary)] shadow-xs">
                  <IconBot className="h-3.5 w-3.5" />
                </div>
                <div className="flex items-center gap-1.5 rounded-[var(--radius-lg)] bg-[var(--surface-soft)] px-4 py-3 shadow-2xs">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--ink)] [animation-delay:-0.3s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--ink)] [animation-delay:-0.15s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--ink)]" />
                </div>
              </div>
            )}

            {displayedAnswer && (
              <div className="flex gap-3">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--on-primary)]">
                  <IconBot className="h-3.5 w-3.5" />
                </div>
                <div className="max-w-[80%] rounded-[var(--radius-lg)] bg-[var(--surface-soft)] px-4 py-2.5 text-[13px] leading-relaxed text-[var(--ink)]">
                  <Markdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                      ul: ({ children }) => <ul className="my-2 list-disc pl-5 space-y-1">{children}</ul>,
                      ol: ({ children }) => <ol className="my-2 list-decimal pl-5 space-y-1">{children}</ol>,
                      li: ({ children }) => <li className="pl-1">{children}</li>,
                      strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                    }}
                  >
                    {cleanMarkdownForDisplay(displayedAnswer)}
                  </Markdown>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="border-t border-[var(--hairline)] bg-[var(--surface-soft)] px-3 py-3">
            <div className="flex items-end gap-2 rounded-[var(--radius-md)] border border-[var(--hairline)] bg-[var(--canvas)] px-3 py-2 focus-within:border-[var(--ink)]">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                rows={1}
                placeholder={t("chat.widget.placeholder")}
                aria-label="Chat input"
                className="min-h-[36px] max-h-[100px] flex-1 resize-none bg-transparent text-[13px] leading-relaxed text-[var(--ink)] placeholder:text-[var(--muted-soft)] focus:outline-none"
              />
              <div className="flex items-center gap-1.5 shrink-0">
                {speech.supported && (
                  <button
                    type="button"
                    aria-label={listening ? "Stop mic" : "Use mic"}
                    onClick={toggleMic}
                    className={`flex h-8 w-8 items-center justify-center rounded-full transition-colors ${
                      listening
                        ? "bg-[var(--ink)] text-[var(--on-primary)] animate-pulse"
                        : "text-[var(--body)] hover:bg-[var(--cream)] hover:text-[var(--ink)]"
                    }`}
                  >
                    <IconMic className="h-4 w-4" />
                  </button>
                )}
                <button
                  type="button"
                  aria-label="Send"
                  disabled={!input.trim() || typing}
                  onClick={() => ask()}
                  className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--ink)] text-[var(--on-primary)] transition-all hover:scale-105 active:scale-95 disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  <IconSend className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
