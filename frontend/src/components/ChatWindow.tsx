import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { Link, useSearchParams, useNavigate } from "react-router-dom";
import { sendChat, sendChatStream, ChatResponse, type StreamEvent, type StepEvent } from "@/lib/api";
import { apiFetch } from "@/lib/backend";
import { useI18n } from "@/lib/i18n/provider";
import type { Locale } from "@/lib/i18n/i18n";
import { formatSchemeQuestion, formatServiceQuestion, formatLegalQuestion } from "@/lib/i18n/formatQuery";
import { createSpeechService } from "@/lib/speech";
import { MessageBubble } from "./chat/MessageBubble";
import { ThinkingProcess } from "./chat/ThinkingProcess";
import { LanguageSwitcher } from "@/components/layout/LanguageSwitcher";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { Reveal } from "@/components/motion/Reveal";
import {
  IconMic,
  IconTrash,
  IconSparkles,
  IconSend,
  IconSidebar,
  IconClock,
  IconBot,
  IconArrowLeft,
  IconPin,
  IconSearch,
  IconEdit,
  IconShare,
  IconUser,
  IconCompass,
  IconX,
} from "@/components/ui/Icons";

type Msg = {
  role: "user" | "assistant";
  text?: string;
  resp?: ChatResponse;
  steps?: StepEvent[];
  thinkingDurationSec?: number;
};

interface Conversation {
  id: string;
  title: string;
  messages: Msg[];
  createdAt: number;
  updatedAt?: number;
  pinned?: boolean;
}

const STORAGE_KEY = "jansahay_conversations";
const ACTIVE_CONV_KEY = "jansahay_active_conv";
const MODELS = [
  { id: "static", label: "JanSahay v1", desc: "Static RAG" },
  { id: "web", label: "JanSahay v2", desc: "Web Search" },
  { id: "rag_web", label: "JanSahay v3", desc: "RAG + Web" },
] as const;

function loadConversations(): Conversation[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveConversations(convs: Conversation[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(convs));
  } catch {
    // localStorage full or unavailable
  }
}

// Re-translate a previously received answer into the current UI language via the
// FastAPI backend. Falls back to the original text if translation is
// unavailable/unconfigured so the UI stays functional.
async function translate(text: string, locale: Locale): Promise<string> {
  try {
    const res = await apiFetch("/api/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // FastAPI's field name is `target_language`; the old BFF payload used
      // `to`, which the backend ignored.
      body: JSON.stringify({ texts: [text], target_language: locale }),
    });
    if (!res.ok) return text;
    const data = (await res.json()) as { translations?: string[] };
    return data.translations?.[0] ?? text;
  } catch {
    return text;
  }
}

function fallback(lang: Locale): ChatResponse {
  return {
    answer:
      lang === "hi"
        ? "सेवा अभी उपलब्ध नहीं है।"
        : lang === "gu"
        ? "સેવા હમણાં ઉપલબ્ધ નથી."
        : lang === "mr"
        ? "सेवा सध्या उपलब्ध नाही."
        : lang === "bn"
        ? "সেবা এখন পর্যন্ত পাওয়া যাচ্ছে না।"
        : lang === "ta"
        ? "சேவை தற்போது கிடைக்கவில்லை."
        : "Service unavailable right now.",
    language: lang,
    domain: "unknown",
    intent: "unknown",
    entities: [],
    confidence: 0,
    confidence_level: "none",
    citations: [],
    abstained: true,
    transport_error: true,
    follow_up_question: null,
  };
}

export function ChatWindow() {
  const router = useNavigate();
  const { t, locale } = useI18n();
  const speech = useMemo(() => createSpeechService(), []);
  const [speechReady, setSpeechReady] = useState(false);
  const [sp] = useSearchParams();
  const [micSupported, setMicSupported] = useState(false);
  useEffect(() => setMicSupported(speech.supported), [speech]);
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  const [input, setInput] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>(() => {
    if (typeof window === "undefined") return [];
    const convs = loadConversations();
    const savedId = localStorage.getItem(ACTIVE_CONV_KEY);
    if (savedId) {
      const conv = convs.find((c) => c.id === savedId);
      if (conv) return conv.messages;
    }
    return [];
  });
  const [typing, setTyping] = useState(false);
  const [listening, setListening] = useState(false);
  const [model, setModel] = useState<typeof MODELS[number]["id"]>("rag_web");
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    if (typeof window === "undefined") return [];
    return loadConversations();
  });
  const [activeConvId, setActiveConvId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    const savedId = localStorage.getItem(ACTIVE_CONV_KEY);
    const convs = loadConversations();
    if (savedId && convs.find((c) => c.id === savedId)) return savedId;
    return null;
  });
  const [searchQuery, setSearchQuery] = useState("");
  const [showSearchInput, setShowSearchInput] = useState(false);
  const [sessionId] = useState(() => crypto.randomUUID());
  const cancelListen = useRef<(() => void) | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const modelPickerRef = useRef<HTMLDivElement>(null);
  const [explicitPending, setExplicitPending] = useState(false);
  const prevLocaleRef = useRef<Locale>(locale);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const lang: Locale = locale;

  // Streaming state
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [streamingMeta, setStreamingMeta] = useState<Record<string, unknown> | null>(null);
  const [streamingSteps, setStreamingSteps] = useState<StepEvent[]>([]);
  const streamingStepsRef = useRef<StepEvent[]>([]);
  const sendStartTimeRef = useRef<number>(0);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const tokenBufferRef = useRef("");

  // Client-only speech readiness
  useEffect(() => {
    setSpeechReady(true);
  }, []);

  // Close model picker on outside click
  useEffect(() => {
    if (!showModelPicker) return;
    function handleClickOutside(e: MouseEvent) {
      if (modelPickerRef.current && !modelPickerRef.current.contains(e.target as Node)) {
        setShowModelPicker(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showModelPicker]);

  // Auto-expand sidebar on large screens
  useEffect(() => {
    if (typeof window !== "undefined" && window.innerWidth >= 1024) {
      setSidebarOpen(true);
    }
  }, []);

  // Auto-save current conversation when msgs change
  // Flag the next message as an explicit language choice when the UI language
  // changes (covers the first switch away from the default too). Consumed + cleared
  // by ask().
  useEffect(() => {
    if (prevLocaleRef.current !== lang) {
      prevLocaleRef.current = lang;
      setExplicitPending(true);
    }
  }, [lang]);

  const initialHistory = useMemo(
    () => [t("chat.starter1"), t("chat.starter2"), t("chat.starter3"), t("chat.starter4")],
    [t]
  );
  useEffect(() => {
    if (msgs.length === 0 || !activeConvId) return;
    setConversations((prev) => {
      const next = prev.map((c) =>
        c.id === activeConvId
          ? { ...c, messages: msgs, updatedAt: Date.now() }
          : c
      );
      saveConversations(next);
      return next;
    });
  }, [msgs, activeConvId]);

  // Create a new conversation
  const createConversation = useCallback((firstMsg: Msg) => {
    const conv: Conversation = {
      id: crypto.randomUUID(),
      title: firstMsg.text?.slice(0, 50) || "New Chat",
      messages: [firstMsg],
      createdAt: Date.now(),
      updatedAt: Date.now(),
      pinned: false,
    };
    setConversations((prev) => {
      const next = [conv, ...prev];
      saveConversations(next);
      return next;
    });
    setActiveConvId(conv.id);
    localStorage.setItem(ACTIVE_CONV_KEY, conv.id);
    setMsgs([firstMsg]);
    return conv.id;
  }, []);

  // Load a conversation from sidebar
  const loadConversation = useCallback((conv: Conversation) => {
    setMsgs(conv.messages);
    setActiveConvId(conv.id);
    localStorage.setItem(ACTIVE_CONV_KEY, conv.id);
    if (typeof window !== "undefined" && window.innerWidth < 1024) {
      setSidebarOpen(false);
    }
  }, []);

  // Pin/Unpin a conversation
  const togglePinConversation = useCallback((convId: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setConversations((prev) => {
      const next = prev.map((c) =>
        c.id === convId ? { ...c, pinned: !c.pinned } : c
      );
      saveConversations(next);
      return next;
    });
  }, []);

  // Delete a conversation
  const deleteConversation = useCallback(
    (convId: string, e: React.MouseEvent) => {
      e.stopPropagation();
      setConversations((prev) => {
        const next = prev.filter((c) => c.id !== convId);
        saveConversations(next);
        return next;
      });
      if (activeConvId === convId) {
        setMsgs([]);
        setActiveConvId(null);
        localStorage.removeItem(ACTIVE_CONV_KEY);
      }
    },
    [activeConvId]
  );

  // Smart auto-scroll: only scroll if user is near bottom
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);

  const checkIfNearBottom = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const { scrollTop, scrollHeight, clientHeight } = container;
    isNearBottomRef.current = scrollHeight - scrollTop - clientHeight < 150;
  }, []);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.addEventListener("scroll", checkIfNearBottom, { passive: true });
    checkIfNearBottom();
    return () => container.removeEventListener("scroll", checkIfNearBottom);
  }, [checkIfNearBottom]);

  const scrollToBottom = useCallback(() => {
    if (isNearBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "auto" });
    }
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [msgs, typing, streamingAnswer, scrollToBottom]);

  // Auto-grow composer
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  }, [input]);

  useEffect(() => {
    const q = sp?.get("q") || (typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("q") : null);
    const scheme = sp?.get("scheme") || (typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("scheme") : null);
    const schemeName = sp?.get("name") || (typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("name") : null);
    if (q) {
      let formattedQ = q;
      const tellMeMatch = q.match(/^Tell me about (.+?)(?: scheme)?$/i);
      const useServiceMatch = q.match(/^How do I use the (.+?) service\?$/i);
      if (tellMeMatch) {
        formattedQ = formatSchemeQuestion(tellMeMatch[1], lang);
      } else if (useServiceMatch) {
        formattedQ = formatServiceQuestion(useServiceMatch[1], lang);
      }
      setInput(formattedQ);
      setMsgs([]);
      setActiveConvId(null);
    } else if (scheme) {
      if (scheme === "pmfby") {
        setInput(t("chat.starter1"));
      } else {
        const nameToUse = schemeName || scheme.replace(/-/g, " ");
        setInput(formatSchemeQuestion(nameToUse, lang));
      }
      setMsgs([]);
      setActiveConvId(null);
    }
  }, [sp, t, lang]);

  async function ask(q?: string) {
    const question = (q ?? input).trim();
    if (!question || typing) return;
    setInput("");

    const userMsg: Msg = { role: "user", text: question };

    if (!activeConvId) {
      createConversation(userMsg);
    } else {
      setMsgs((m) => [...m, userMsg]);
    }

    if (typeof window !== "undefined" && window.innerWidth < 1024) {
      setSidebarOpen(false);
    }

    const uiLanguageExplicit = explicitPending;
    setExplicitPending(false);

    setTyping(true);
    setStreamingAnswer("");
    setStreamingMeta(null);
    setIsStreaming(true);
    tokenBufferRef.current = "";
    sendStartTimeRef.current = Date.now();
    const initialSteps: StepEvent[] = [
      {
        id: "retrieval_start",
        label: "Searching Knowledge Base",
        detail: "Initiating multi-source retrieval",
        status: "active",
      },
      {
        id: "evidence_merge",
        label: "Merging Evidence",
        detail: "Cross-referencing legal provisions & circulars",
        status: "pending",
      },
      {
        id: "llm_generate",
        label: "Generating Response",
        detail: "Synthesizing verified citizen guidance",
        status: "pending",
      },
      {
        id: "citation_verify",
        label: "Verifying Citations",
        detail: "Checking source grounding against official documents",
        status: "pending",
      },
    ];
    streamingStepsRef.current = initialSteps;
    setStreamingSteps(initialSteps);

    const history = msgs
      .map((m) => {
        const content = m.role === "user" ? m.text : m.resp?.answer || m.text;
        return content ? { role: m.role, content } : null;
      })
      .filter((m): m is { role: "user" | "assistant"; content: string } => m !== null)
      .slice(-8);

    const abortController = new AbortController();
    abortRef.current = abortController;

    let metaSnapshot: Record<string, unknown> = {};

    try {
      await sendChatStream(
        { question, session_id: sessionId, language: lang, state: null, history, ui_language_explicit: uiLanguageExplicit, mode: model },
        (event: StreamEvent) => {
          if (event.event === "token") {
            const text = (event.data.text as string).replace(/INSUFFICIENT_EVIDENCE/g, "");
            if (text) {
              tokenBufferRef.current += text;
              setStreamingAnswer(tokenBufferRef.current);
            }
          } else if (event.event === "step") {
            const step = event.data;
            setStreamingSteps((prev) => {
              const idx = prev.findIndex((s) => s.id === step.id);
              let next: StepEvent[];
              if (idx >= 0) {
                next = [...prev];
                next[idx] = { ...next[idx], ...step };
              } else {
                next = [...prev, step];
              }
              streamingStepsRef.current = next;
              return next;
            });
          } else if (event.event === "thinking") {
            const text = (event.data as { text?: string }).text;
            if (text) {
              setStreamingSteps((prev) => {
                const idx = prev.findIndex((s) => s.id === "retrieval_start");
                let next: StepEvent[];
                if (idx >= 0) {
                  next = [...prev];
                  next[idx] = { ...next[idx], detail: text };
                } else {
                  next = [{ id: "retrieval_start", label: "Searching Knowledge Base", detail: text, status: "active" as const }, ...prev];
                }
                streamingStepsRef.current = next;
                return next;
              });
            }
          } else if (event.event === "metadata") {
            metaSnapshot = event.data;
            setStreamingMeta(event.data);
          } else if (event.event === "error") {
            console.error("Stream error:", event.data.message);
          }
        },
        abortController.signal,
      );

      // Build final response from ref (synchronous, no stale state)
      const finalAnswer = tokenBufferRef.current.replace(/INSUFFICIENT_EVIDENCE/g, "").trim();
      const thinkingDurationSec = Math.max(1, Math.round((Date.now() - sendStartTimeRef.current) / 1000));
      const finalSteps: StepEvent[] = streamingStepsRef.current.map((s) => ({
        ...s,
        status: "completed" as const,
      }));

      const finalResp: ChatResponse = {
        answer: finalAnswer,
        language: (metaSnapshot.language as Locale) || lang,
        domain: (metaSnapshot.domain as string) || "unknown",
        intent: (metaSnapshot.domain as string) || "unknown",
        entities: [],
        confidence: (metaSnapshot.confidence as number) || 0,
        confidence_level: (metaSnapshot.confidence_level as ChatResponse["confidence_level"]) || "none",
        citations: (metaSnapshot.citations as ChatResponse["citations"]) || [],
        abstained: (metaSnapshot.abstained as boolean) || false,
        follow_up_question: null,
        mode: (metaSnapshot.mode as string) || undefined,
        grievance_stage: (metaSnapshot.grievance_stage as ChatResponse["grievance_stage"]) || undefined,
        grievance_finalized: (metaSnapshot.grievance_finalized as boolean) || undefined,
        grievance: (metaSnapshot.grievance as ChatResponse["grievance"]) || undefined,
        grievance_draft_summary: (metaSnapshot.grievance_draft_summary as ChatResponse["grievance_draft_summary"]) || undefined,
        grievance_fields_schema: (metaSnapshot.grievance_fields_schema as ChatResponse["grievance_fields_schema"]) || undefined,
        conversation_id: (metaSnapshot.conversation_id as string) || undefined,
        speech_segments: (metaSnapshot.speech_segments as ChatResponse["speech_segments"]) || undefined,
      };
      setMsgs((m) => [
        ...m,
        {
          role: "assistant",
          resp: finalResp,
          steps: finalSteps.length > 0 ? finalSteps : undefined,
          thinkingDurationSec,
        },
      ]);
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      const assistantMsg: Msg = { role: "assistant", resp: fallback(lang) };
      setMsgs((m) => [...m, assistantMsg]);
    } finally {
      setTyping(false);
      setIsStreaming(false);
      setStreamingAnswer("");
      setStreamingMeta(null);
      setStreamingSteps([]);
      streamingStepsRef.current = [];
      tokenBufferRef.current = "";
      abortRef.current = null;
    }
  }

  function handleNewChat() {
    setMsgs([]);
    setInput("");
    setActiveConvId(null);
    localStorage.removeItem(ACTIVE_CONV_KEY);
    if (typeof window !== "undefined" && window.innerWidth < 1024) {
      setSidebarOpen(false);
    }
  }

  function handleBack() {
    if (window.history.length > 1) {
      router(-1);
    } else {
      router("/");
    }
  }

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
    cancelListen.current = speech.listen(
      lang,
      (text) => {
        setInput((prev) => (prev ? prev + " " : "") + text);
        setListening(false);
      },
      (err: string) => {
        console.error("Speech recognition error:", err);
        setListening(false);
      },
    );
    setListening(true);
  }

  const suggestedActions = [
    { icon: "🌾", label: t("nav.schemes") || "Crop Insurance", prompt: t("chat.starter1") },
    { icon: "⚡", label: t("nav.services") || "Services", prompt: t("chat.starter2") },
    { icon: "🏛️", label: t("nav.library") || "PACS Services", prompt: t("chat.starter3") },
    { icon: "⚖️", label: t("nav.legal") || "Legal Framework", prompt: t("chat.starter4") },
  ];

  function formatTime(ts: number) {
    const d = new Date(ts);
    const now = new Date();
    if (d.toDateString() === now.toDateString()) {
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  // Filter conversations
  const filteredConversations = useMemo(() => {
    if (!searchQuery.trim()) return conversations;
    return conversations.filter((c) =>
      c.title.toLowerCase().includes(searchQuery.toLowerCase())
    );
  }, [conversations, searchQuery]);

  const pinnedConversations = useMemo(() => {
    return filteredConversations.filter((c) => c.pinned);
  }, [filteredConversations]);

  const recentConversations = useMemo(() => {
    return filteredConversations.filter((c) => !c.pinned);
  }, [filteredConversations]);

  return (
    <div className="relative flex h-dvh w-full overflow-hidden bg-[var(--canvas)] text-[var(--ink)] font-sans">
      {/* Mobile Backdrop Overlay */}
      {sidebarOpen && (
        <div
          onClick={() => setSidebarOpen(false)}
          className="fixed inset-0 z-30 bg-black/50 backdrop-blur-xs lg:hidden"
          aria-hidden="true"
        />
      )}

      {/* ==================== LEFT SIDEBAR ==================== */}
      {/* Collapsed Rail (desktop icon sidebar like ChatGPT) */}
      {!sidebarOpen && (
        <aside className="hidden lg:flex inset-y-0 left-0 z-40 w-16 flex-col items-center border-r border-[var(--hairline)] bg-[var(--surface-soft)] py-3">
          {/* Toggle Sidebar */}
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            title={t("chat.openSidebar")}
            className="flex h-9 w-9 items-center justify-center rounded-[var(--radius-md)] text-[var(--body)] transition-colors hover:bg-[var(--surface-card)] hover:text-[var(--ink)]"
          >
            <IconSidebar className="h-5 w-5" />
          </button>

          {/* New Chat Icon */}
          <button
            type="button"
            onClick={handleNewChat}
            title={t("chat.newChat")}
            className="mt-2 flex h-9 w-9 items-center justify-center rounded-[var(--radius-md)] text-[var(--body)] transition-colors hover:bg-[var(--surface-card)] hover:text-[var(--ink)]"
          >
            <IconEdit className="h-5 w-5" />
          </button>

          <div className="my-2 h-[1px] w-8 bg-[var(--hairline)]" />

          {/* Icon List of Conversations */}
          <div suppressHydrationWarning className="flex-1 w-full overflow-y-auto space-y-1.5 px-2">
            {hydrated && conversations.map((conv) => (
              <button
                key={conv.id}
                type="button"
                onClick={() => loadConversation(conv)}
                title={conv.title}
                className={`group flex h-9 w-full items-center justify-center rounded-[var(--radius-md)] transition-colors hover:bg-[var(--surface-card)] ${
                  activeConvId === conv.id ? "bg-[var(--surface-card)] text-[var(--ink)]" : "text-[var(--muted-soft)]"
                }`}
              >
                {conv.pinned ? (
                  <IconPin className="h-4 w-4 shrink-0 text-[var(--ink)]" />
                ) : (
                  <IconClock className="h-4 w-4 shrink-0 group-hover:text-[var(--ink)]" />
                )}
              </button>
            ))}
          </div>

          {/* Footer User Profile */}
          <div className="mt-auto pt-2">
            <Link
              to="/"
              className="flex h-9 w-9 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--on-primary)] shadow-xs transition-transform hover:scale-105"
              title={t("chat.home")}
            >
              <IconBot className="h-5 w-5" />
            </Link>
          </div>
        </aside>
      )}

      {/* Expanded Sidebar (ChatGPT Style) */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex flex-col border-r border-[var(--hairline)] bg-[var(--surface-soft)] transition-all duration-300 lg:relative lg:z-0 ${
          sidebarOpen
            ? "w-72 min-w-[18rem] translate-x-0 shadow-2xl lg:shadow-none"
            : "w-0 min-w-0 -translate-x-full overflow-hidden lg:hidden"
        }`}
      >
        {/* Sidebar Header with ChatGPT-like Icons */}
        <div className="flex items-center justify-between p-3 border-b border-[var(--hairline)]/60">
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setSidebarOpen(false)}
              title={t("chat.closeSidebar")}
              className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] text-[var(--body)] transition-colors hover:bg-[var(--surface-card)] hover:text-[var(--ink)]"
            >
              <IconSidebar className="h-4.5 w-4.5" />
            </button>
          </div>

          <div className="flex items-center gap-1">
            {/* Search Toggle */}
            <button
              type="button"
              onClick={() => setShowSearchInput((s) => !s)}
              title={t("chat.searchHistory")}
              className={`flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] transition-colors hover:bg-[var(--surface-card)] ${
                showSearchInput ? "bg-[var(--surface-card)] text-[var(--ink)]" : "text-[var(--body)]"
              }`}
            >
              <IconSearch className="h-4 w-4" />
            </button>

            {/* New Chat Button */}
            <button
              type="button"
              onClick={handleNewChat}
              title={t("chat.newChat")}
              className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] text-[var(--body)] transition-colors hover:bg-[var(--surface-card)] hover:text-[var(--ink)]"
            >
              <IconEdit className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Search Input Bar (if open) */}
        {showSearchInput && (
          <div className="px-3 pt-2.5 pb-1">
            <div className="relative flex items-center rounded-[var(--radius-md)] border border-[var(--hairline)] bg-[var(--canvas)] px-2.5 py-1.5 shadow-2xs">
              <IconSearch className="h-3.5 w-3.5 shrink-0 text-[var(--muted-soft)]" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t("chat.searchPlaceholder")}
                className="w-full bg-transparent px-2 text-xs text-[var(--ink)] placeholder:text-[var(--muted-soft)] focus:outline-none"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  className="text-[var(--muted-soft)] hover:text-[var(--ink)]"
                >
                  <IconX className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
        )}

        {/* Main Sidebar Navigation & History List */}
        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-4 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
          {/* New Session Button */}
          <button
            type="button"
            onClick={handleNewChat}
            className="flex w-full items-center gap-2.5 rounded-[var(--radius-md)] px-2.5 py-2 text-left text-xs font-semibold transition-colors hover:bg-[var(--surface-card)] text-[var(--ink)]"
          >
            <IconEdit className="h-4 w-4 text-[var(--ink)] shrink-0" />
            <span>{t("common.newSession")}</span>
          </button>

          {/* PINNED SECTION */}
          {hydrated && pinnedConversations.length > 0 && (
            <div>
              <div className="mb-1.5 flex items-center justify-between px-2 text-[11px] font-bold uppercase tracking-wider text-[var(--muted)]">
                <span className="flex items-center gap-1.5">
                  <IconPin className="h-3.5 w-3.5 text-[var(--ink)]" />
                  {t("chat.pinned")}
                </span>
                <span className="text-[10px] text-[var(--muted-soft)] font-mono">{pinnedConversations.length}</span>
              </div>
              <div className="space-y-0.5">
                {pinnedConversations.map((conv) => (
                  <div
                    key={conv.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => loadConversation(conv)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        loadConversation(conv);
                      }
                    }}
                    className={`group flex w-full cursor-pointer items-center gap-2.5 rounded-[var(--radius-md)] px-2.5 py-2 text-left text-xs font-medium transition-colors hover:bg-[var(--surface-card)] ${
                      activeConvId === conv.id
                        ? "bg-[var(--surface-card)] font-semibold text-[var(--ink)] border-l-2 border-[var(--ink)]"
                        : "text-[var(--ink)]"
                    }`}
                  >
                    <IconPin className="h-3.5 w-3.5 shrink-0 text-[var(--ink)]" />
                    <div className="min-w-0 flex-1">
                      <span className="block truncate">{conv.title}</span>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => togglePinConversation(conv.id, e)}
                      title={t("chat.unpin")}
                      className="shrink-0 p-1 text-[var(--ink)] hover:opacity-75"
                    >
                      <IconPin className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* RECENT HISTORY SECTION */}
          <div>
            <div className="mb-1.5 flex items-center justify-between px-2 text-[11px] font-bold uppercase tracking-wider text-[var(--muted)]">
              <span className="flex items-center gap-1.5">
                <IconClock className="h-3.5 w-3.5 text-[var(--muted)]" />
                {t("chat.recentHistory")}
              </span>
              {hydrated && conversations.length > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    setConversations([]);
                    saveConversations([]);
                    setMsgs([]);
                    setActiveConvId(null);
                  }}
                  title={t("chat.clearHistory")}
                  className="text-[var(--muted-soft)] hover:text-[var(--state-error)] transition-colors"
                >
                  <IconTrash className="h-3.5 w-3.5" />
                </button>
              )}
            </div>

            <div className="space-y-0.5">
              {hydrated && recentConversations.length === 0 && pinnedConversations.length === 0 && (
                <p className="px-2 py-6 text-center text-xs text-[var(--muted-soft)] italic">
                  {t("chat.noHistory")}
                </p>
              )}

              {hydrated && recentConversations.map((conv) => (
                <div
                  key={conv.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => loadConversation(conv)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      loadConversation(conv);
                    }
                  }}
                  className={`group flex w-full cursor-pointer items-center gap-2.5 rounded-[var(--radius-md)] px-2.5 py-2 text-left text-xs font-medium transition-colors hover:bg-[var(--surface-card)] ${
                    activeConvId === conv.id
                      ? "bg-[var(--surface-card)] font-semibold text-[var(--ink)] border-l-2 border-[var(--ink)]"
                      : "text-[var(--ink)]"
                  }`}
                >
                  <IconClock className="h-3.5 w-3.5 shrink-0 text-[var(--muted-soft)] group-hover:text-[var(--ink)]" />
                  <div className="min-w-0 flex-1">
                    <span className="block truncate">{conv.title}</span>
                    <span className="text-[10px] text-[var(--muted-soft)] block truncate">
                      {formatTime(conv.updatedAt || conv.createdAt)}
                    </span>
                  </div>
                  <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      type="button"
                      onClick={(e) => togglePinConversation(conv.id, e)}
                      title={t("chat.pinChat")}
                      className="p-1 text-[var(--muted-soft)] hover:text-[var(--ink)]"
                    >
                      <IconPin className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      onClick={(e) => deleteConversation(conv.id, e)}
                      title={t("chat.delete")}
                      className="p-1 text-[var(--muted-soft)] hover:text-[var(--state-error)]"
                    >
                      <IconTrash className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Sidebar Footer with User Account */}
        <div className="border-t border-[var(--hairline)] p-3">
          <div className="flex items-center gap-3 rounded-[var(--radius-md)] bg-[var(--canvas)] p-2 shadow-2xs">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--on-primary)]">
              <IconUser className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-semibold text-[var(--ink)]">{t("chat.user")}</p>
              <p className="truncate text-[10px] text-[var(--muted-soft)] font-mono">{t("chat.freePlan")}</p>
            </div>
          </div>
        </div>
      </aside>

      {/* ==================== MAIN CENTERED CHAT AREA ==================== */}
      <main className="flex flex-1 flex-col overflow-hidden bg-[var(--canvas)] min-w-0">
        {/* Top Header Bar */}
        <header className="flex h-13 shrink-0 items-center justify-between border-b border-[var(--hairline)] bg-[var(--canvas)] px-3 sm:px-4">
          <div className="flex items-center gap-2">
            {/* BACK BUTTON TO LEAVE CHAT ROUTE */}
            <button
              type="button"
              onClick={handleBack}
              title={t("chat.back")}
              className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--hairline)] px-2.5 py-1.5 text-xs font-semibold text-[var(--body)] transition-colors hover:bg-[var(--surface-card)] hover:text-[var(--ink)]"
            >
              <IconArrowLeft className="h-4 w-4" />
              <span className="hidden sm:inline">Back</span>
            </button>

            {/* Sidebar toggle */}
            <button
              type="button"
              onClick={() => setSidebarOpen((s) => !s)}
              title={t("chat.toggleSidebar")}
              className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] border border-[var(--hairline)] text-[var(--body)] transition-colors hover:bg-[var(--surface-card)] hover:text-[var(--ink)]"
            >
              <IconSidebar className="h-4 w-4" />
            </button>
          </div>

          <div className="flex items-center gap-2">
            <LanguageSwitcher />
          </div>
        </header>

        {/* Center Aligned Message Stream Area */}
        <div ref={scrollContainerRef} className="flex-1 overflow-y-auto w-full [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
          <div className="mx-auto w-full max-w-3xl px-4 sm:px-6 py-6 space-y-6">
            {/* Empty State - Welcome + Input Centered */}
            {hydrated && msgs.length === 0 && (
              <Reveal trigger="load">
                <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
                  <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[var(--ink)]">
                    {t("chat.emptyTitle")}
                  </h1>
                  <p className="mt-2 text-sm text-[var(--body)] max-w-md">
                    {t("chat.emptySubtitle")}
                  </p>

                  {/* Suggested questions above input */}
                  <div className="mt-8 w-full max-w-xl">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-4">
                      {suggestedActions.map((action) => (
                        <button
                          key={action.label}
                          type="button"
                          onClick={() => {
                            setInput(action.prompt);
                            taRef.current?.focus();
                          }}
                          className="text-left rounded-[var(--radius-md)] border border-[var(--hairline)] bg-white px-4 py-3 text-sm text-[var(--ink)] transition-all hover:border-[var(--ink)]/40 hover:shadow-sm"
                        >
                          <span className="font-medium">{action.label}</span>
                          <span className="block mt-0.5 text-xs text-[var(--muted)] line-clamp-1">{action.prompt}</span>
                        </button>
                      ))}
                    </div>

                    {/* Centered Input */}
                    <div ref={modelPickerRef} className="ask-input-wrap relative flex items-end gap-1 rounded-3xl border border-[var(--hairline)] bg-white px-2 py-2 shadow-md transition-all focus-within:border-[var(--ink)] focus-within:ring-1 focus-within:ring-[var(--ink)]">
                      {/* Model Selector */}
                      <div className="relative shrink-0 mb-0.5">
                        <button
                          type="button"
                          onClick={() => setShowModelPicker((s) => !s)}
                          className="flex items-center rounded-full bg-[var(--surface-soft)] px-3 py-1.5 text-xs font-semibold text-[var(--ink)] transition-colors hover:bg-[var(--surface-card)]"
                        >
                          {MODELS.find((m) => m.id === model)?.label}
                        </button>
                        {showModelPicker && (
                          <div className="absolute bottom-full left-0 z-50 mb-2 w-56 rounded-[var(--radius-md)] border border-[var(--hairline)] bg-white shadow-lg">
                            {MODELS.map((m) => (
                              <button
                                key={m.id}
                                type="button"
                                onClick={() => {
                                  setModel(m.id);
                                  setShowModelPicker(false);
                                }}
                                className={`flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm transition-colors hover:bg-[var(--surface-card)] ${
                                  model === m.id ? "bg-[var(--surface-soft)] font-semibold" : ""
                                }`}
                              >
                                <span className="flex-1">
                                  <span className="block text-[var(--ink)]">{m.label}</span>
                                  <span className="block text-[10px] text-[var(--muted-soft)]">{m.desc}</span>
                                </span>
                                {model === m.id && (
                                  <span className="text-[var(--ink)]">✓</span>
                                )}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                      <textarea
                        ref={taRef}
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={onKeyDown}
                        rows={1}
                        placeholder={t("chat.placeholder")}
                        aria-label={t("chat.placeholder")}
                        className="min-w-0 flex-1 resize-none bg-transparent px-2 py-1 text-sm leading-relaxed text-[var(--ink)] placeholder:text-[var(--muted-soft)] focus:outline-none max-h-[180px]"
                      />
                      <div className="flex shrink-0 items-center gap-0.5 mb-0.5">
                        {speechReady && speech.supported && (
                          <button
                            type="button"
                            aria-label={listening ? t("common.stopMic") : t("common.mic")}
                            onClick={toggleMic}
                            className={`flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
                              listening
                                ? "bg-[var(--ink)] text-[var(--on-primary)] animate-pulse"
                                : "text-[var(--body)] hover:bg-[var(--surface-card)] hover:text-[var(--ink)]"
                            }`}
                          >
                            <IconMic className="h-3.5 w-3.5" />
                          </button>
                        )}
                        <button
                          type="button"
                          aria-label={t("common.send")}
                          disabled={!input.trim() || typing}
                          onClick={() => ask()}
                          className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--ink)] text-[var(--on-primary)] shadow-sm transition-all hover:scale-105 active:scale-95 disabled:opacity-35 disabled:cursor-not-allowed disabled:hover:scale-100"
                        >
                          <IconSend className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </Reveal>
            )}

            {/* Conversation Messages */}
            {hydrated && (() => {
              let lastAssistantIdx = -1;
              for (let i = msgs.length - 1; i >= 0; i--) {
                if (msgs[i].role === "assistant") {
                  lastAssistantIdx = i;
                  break;
                }
              }
              return msgs.map((m, i) =>
                m.role === "user" ? (
                  <div key={i} className="flex justify-end">
                    <div className="max-w-[85%] sm:max-w-[75%] rounded-[var(--radius-lg)] bg-[var(--primary)] px-4 py-3 text-xs sm:text-sm leading-relaxed text-[var(--on-primary)] shadow-2xs">
                      {m.text}
                    </div>
                  </div>
                ) : (
                  <div key={i} className="flex flex-col gap-2">
                    {m.steps && m.steps.length > 0 && (
                      <ThinkingProcess
                        steps={m.steps}
                        isStreaming={false}
                        isComplete={true}
                        initialDurationSec={m.thinkingDurationSec}
                      />
                    )}
                    <MessageBubble
                      resp={m.resp!}
                    />
                  </div>
                )
              );
            })()}

            {typing && (
              <div className="flex flex-col gap-3 animate-in fade-in duration-200">
                {streamingSteps.length > 0 ? (
                  <ThinkingProcess steps={streamingSteps} isStreaming={Boolean(streamingAnswer.trim())} />
                ) : !streamingAnswer.trim() ? (
                  <div className="flex gap-3 animate-in fade-in duration-200">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--on-primary)] shadow-xs">
                      <IconBot className="h-4 w-4" />
                    </div>
                    <div className="flex items-center gap-1.5 rounded-[var(--radius-lg)] bg-[var(--surface-soft)] px-4 py-3.5 shadow-2xs">
                      <span className="h-2 w-2 animate-bounce rounded-full bg-[var(--ink)] [animation-delay:-0.3s]" />
                      <span className="h-2 w-2 animate-bounce rounded-full bg-[var(--ink)] [animation-delay:-0.15s]" />
                      <span className="h-2 w-2 animate-bounce rounded-full bg-[var(--ink)]" />
                    </div>
                  </div>
                ) : null}

                {isStreaming && streamingAnswer.trim() && (
                  <MessageBubble
                    isStreaming={true}
                    resp={{
                      answer: streamingAnswer,
                      language: lang,
                      domain: (streamingMeta?.domain as string) || "unknown",
                      intent: (streamingMeta?.domain as string) || "unknown",
                      entities: [],
                      confidence: (streamingMeta?.confidence as number) || 0,
                      confidence_level: (streamingMeta?.confidence_level as ChatResponse["confidence_level"]) || "none",
                      citations: (streamingMeta?.citations as ChatResponse["citations"]) || [],
                      abstained: false,
                      follow_up_question: null,
                    }}
                  />
                )}
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Floating Input Composer - only show when there are messages */}
        {hydrated && msgs.length > 0 && (
        <div className="w-full bg-[var(--canvas)] pb-3 pt-2">
          <div className="mx-auto w-full max-w-3xl px-4 sm:px-6">
            <div ref={modelPickerRef} className="ask-input-wrap relative flex items-end gap-1 rounded-3xl border border-[var(--hairline)] bg-[var(--surface-soft)] px-2 py-2 shadow-md transition-all focus-within:border-[var(--ink)] focus-within:ring-1 focus-within:ring-[var(--ink)]">
              {/* Model Selector */}
              <div className="relative shrink-0 mb-0.5">
                <button
                  type="button"
                  onClick={() => setShowModelPicker((s) => !s)}
                  className="flex items-center rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-[var(--ink)] transition-colors hover:bg-[var(--surface-card)]"
                >
                  {MODELS.find((m) => m.id === model)?.label}
                </button>
                {showModelPicker && (
                  <div className="absolute bottom-full left-0 z-50 mb-2 w-56 rounded-[var(--radius-md)] border border-[var(--hairline)] bg-white shadow-lg">
                    {MODELS.map((m) => (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => {
                          setModel(m.id);
                          setShowModelPicker(false);
                        }}
                        className={`flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm transition-colors hover:bg-[var(--surface-card)] ${
                          model === m.id ? "bg-[var(--surface-soft)] font-semibold" : ""
                        }`}
                      >
                        <span className="flex-1">
                          <span className="block text-[var(--ink)]">{m.label}</span>
                          <span className="block text-[10px] text-[var(--muted-soft)]">{m.desc}</span>
                        </span>
                        {model === m.id && (
                          <span className="text-[var(--ink)]">✓</span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <textarea
                ref={taRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                rows={1}
                placeholder={t("chat.placeholder")}
                aria-label={t("chat.placeholder")}
                className="min-w-0 flex-1 resize-none bg-transparent px-2 py-1 text-sm leading-relaxed text-[var(--ink)] placeholder:text-[var(--muted-soft)] focus:outline-none max-h-[180px]"
              />
              <div className="flex shrink-0 items-center gap-0.5 mb-0.5">
                {speechReady && speech.supported && (
                  <button
                    type="button"
                    aria-label={listening ? t("common.stopMic") : t("common.mic")}
                    onClick={toggleMic}
                    className={`flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
                      listening
                        ? "bg-[var(--ink)] text-[var(--on-primary)] animate-pulse"
                        : "text-[var(--body)] hover:bg-[var(--surface-card)] hover:text-[var(--ink)]"
                    }`}
                  >
                    <IconMic className="h-3.5 w-3.5" />
                  </button>
                )}
                <button
                  type="button"
                  aria-label={t("common.send")}
                  disabled={!input.trim() || typing}
                  onClick={() => ask()}
                  className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--ink)] text-[var(--on-primary)] shadow-sm transition-all hover:scale-105 active:scale-95 disabled:opacity-35 disabled:cursor-not-allowed disabled:hover:scale-100"
                >
                  <IconSend className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {/* Sub-caption Disclaimer Centered */}
            <p className="mt-2 text-center text-[10px] sm:text-xs text-[var(--muted-soft)]">
              {t("chat.disclaimer")}
            </p>
          </div>
        </div>
        )}
      </main>
    </div>
  );
}
