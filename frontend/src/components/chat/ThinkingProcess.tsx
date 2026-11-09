import { useState, useEffect, useRef, useMemo } from "react";
import { IconChevronDown } from "@/components/ui/Icons";
import type { StepEvent } from "@/lib/api";
import styles from "./ThinkingProcess.module.css";

interface ThinkingProcessProps {
  steps: StepEvent[];
  lang?: string;
  isStreaming: boolean;
  isComplete?: boolean;
  initialDurationSec?: number;
}

const STEP_ORDER = [
  "retrieval_start",
  "static_done",
  "web_done",
  "evidence_merge",
  "llm_generate",
  "citation_verify",
];

const CYCLING_THOUGHTS: Record<string, string[]> = {
  retrieval_start: [
    "Querying PACS bylaws & central cooperative guidelines...",
    "Scanning PMFBY operational guidelines & state portals...",
    "Retrieving verified government scheme documentation...",
    "Checking legal provisions & regulatory circulars...",
  ],
  evidence_merge: [
    "Analyzing evidence from official documents & web...",
    "Evaluating conditionality & eligibility requirements...",
    "Ranking relevance & grounding confidence...",
  ],
  llm_generate: [
    "Synthesizing verified citizen-grounded response...",
    "Formulating clear, actionable guidance...",
    "Drafting in requested language...",
  ],
  citation_verify: [
    "Validating citation chunks against source documents...",
    "Ensuring strict factual grounding without hallucination...",
  ],
};

function Spinner() {
  return (
    <svg className="h-3.5 w-3.5 animate-spin text-[var(--primary)]" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg className="h-3.5 w-3.5 text-[var(--success,#22c55e)] shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <path strokeLinecap="round" strokeLinejoin="round" d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function SparkleIcon() {
  return (
    <svg className="h-3.5 w-3.5 text-[var(--brand-teal,#1a3a3a)] shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z"
      />
    </svg>
  );
}

function sortSteps(steps: StepEvent[]): StepEvent[] {
  return [...steps].sort((a, b) => {
    const ai = STEP_ORDER.indexOf(a.id);
    const bi = STEP_ORDER.indexOf(b.id);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });
}

export function ThinkingProcess({
  steps,
  isStreaming,
  isComplete = false,
  initialDurationSec,
}: ThinkingProcessProps) {
  const [expanded, setExpanded] = useState(!isStreaming && !isComplete);
  const [elapsedSec, setElapsedSec] = useState(initialDurationSec ?? 0);
  const [thoughtIdx, setThoughtIdx] = useState(0);
  const startTimeRef = useRef<number | null>(null);

  // Elapsed time counter: ticks while thinking, locks once streaming or complete
  useEffect(() => {
    if (isStreaming || isComplete) return;

    const now = Date.now();
    startTimeRef.current = now;
    const timer = setInterval(() => {
      const start = startTimeRef.current ?? now;
      setElapsedSec(Math.max(1, Math.floor((Date.now() - start) / 1000)));
    }, 1000);
    return () => clearInterval(timer);
  }, [isStreaming, isComplete]);

  // Dynamic cycling thoughts to ensure user never sees a static/frozen description
  useEffect(() => {
    if (isStreaming || isComplete) return;
    const ticker = setInterval(() => {
      setThoughtIdx((prev) => prev + 1);
    }, 2200);
    return () => clearInterval(ticker);
  }, [isStreaming, isComplete]);

  const sorted = useMemo(() => sortSteps(steps), [steps]);
  const allComplete = sorted.length > 0 && sorted.every((s) => s.status === "completed");
  const completedCount = sorted.filter((s) => s.status === "completed").length;
  const activeStep = sorted.find((s) => s.status === "active");

  if (sorted.length === 0) return null;

  const currentCyclingThought = activeStep
    ? (CYCLING_THOUGHTS[activeStep.id] || CYCLING_THOUGHTS.retrieval_start)[
        thoughtIdx % (CYCLING_THOUGHTS[activeStep.id] || CYCLING_THOUGHTS.retrieval_start).length
      ]
    : "Analyzing...";

  const summaryText = allComplete
    ? `${completedCount} steps complete`
    : activeStep?.label || "Processing...";

  const displayDuration =
    (isStreaming || isComplete) && typeof initialDurationSec === "number" && initialDurationSec > 0
      ? initialDurationSec
      : elapsedSec;

  const timeLabel = displayDuration > 0
    ? `Thought for ${displayDuration} second${displayDuration === 1 ? "" : "s"}`
    : "Thought process";

  return (
    <div className="flex flex-col gap-1.5 w-full max-w-3xl my-1 animate-in fade-in duration-200">
      <div
        className={`rounded-2xl border border-[var(--hairline,#e5e5e5)] bg-[var(--surface-soft,#faf5e8)]/80 backdrop-blur-sm transition-all duration-200 overflow-hidden shadow-2xs ${styles.thinkingBar}`}
      >
        {/* When streaming or completed, and collapsed: Sleek Claude/ChatGPT Summary Pill */}
        {(isStreaming || isComplete) && !expanded && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="flex items-center justify-between w-full px-3.5 py-2.5 text-left transition-colors hover:bg-[var(--surface-elevated)]/60 cursor-pointer group"
          >
            <div className="flex items-center gap-2 min-w-0">
              <span className={styles.sparkleGlow}>
                <SparkleIcon />
              </span>
              <span className="text-xs font-semibold text-[var(--ink)]">
                {timeLabel}
              </span>
              <span className="text-xs text-[var(--muted-soft)] hidden sm:inline">•</span>
              <span className="text-sm font-medium text-[var(--body,#3a3a3a)] truncate">
                {summaryText}
              </span>
            </div>
            <IconChevronDown className="h-3.5 w-3.5 text-[var(--muted-soft)] transition-transform duration-200 group-hover:text-[var(--ink)]" />
          </button>
        )}

        {/* When expanded or actively thinking before streaming: Full Process View */}
        {((!isStreaming && !isComplete) || expanded) && (
          <div>
            {/* Header Bar */}
            <div
              role="button"
              tabIndex={0}
              onClick={() => setExpanded((prev) => !prev)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setExpanded((prev) => !prev);
                }
              }}
              className="flex items-center justify-between w-full px-3.5 py-2.5 text-left transition-colors hover:bg-[var(--surface-elevated)]/60 cursor-pointer group select-none"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <span className={styles.sparkleGlow}>
                  <SparkleIcon />
                </span>
                <span className={`text-xs sm:text-sm font-semibold tracking-wide ${styles.shimmerText}`}>
                  {isStreaming || isComplete
                    ? timeLabel
                    : `Thinking (${elapsedSec}s)...`}
                </span>
              </div>

              <div className="flex items-center gap-1.5 shrink-0 pl-2">
                <span className="text-[11px] font-medium text-[var(--muted-soft)] group-hover:text-[var(--ink)] transition-colors hidden sm:inline">
                  {expanded ? "Hide" : "Details"}
                </span>
                <IconChevronDown
                  className={`h-3.5 w-3.5 text-[var(--muted-soft)] transition-transform duration-200 group-hover:text-[var(--ink)] ${
                    expanded ? "rotate-180" : ""
                  }`}
                />
              </div>
            </div>

            {/* Steps Timeline */}
            <div className="px-4 pb-3.5 pt-1 border-t border-[var(--hairline,#e5e5e5)]/60 bg-[var(--canvas)]/40">
              <div className={`flex flex-col gap-2 pt-2 ${styles.timelineTrack}`}>
                {sorted.map((step) => {
                  const isActive = step.status === "active";
                  const isDone = step.status === "completed";

                  return (
                    <div
                      key={step.id}
                      className="flex items-start gap-2.5 animate-in fade-in slide-in-from-top-1 duration-200"
                    >
                      <span className="mt-0.5 shrink-0 z-10 bg-[var(--canvas)] rounded-full p-0.5">
                        {isActive && <Spinner />}
                        {isDone && <CheckIcon />}
                        {step.status === "pending" && (
                          <span className="inline-block h-3.5 w-3.5 rounded-full border-2 border-[var(--muted-soft)] opacity-40" />
                        )}
                      </span>

                      <div className="flex flex-col min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span
                            className={`text-xs sm:text-sm font-medium ${
                              isActive ? "text-[var(--ink)] font-semibold" : "text-[var(--body,#3a3a3a)]"
                            }`}
                          >
                            {step.label}
                          </span>
                          {isActive && (
                            <span className="flex h-1.5 w-1.5 rounded-full bg-[var(--brand-teal,#1a3a3a)] animate-ping shrink-0" />
                          )}
                        </div>

                        {/* Step Detail */}
                        {step.detail && (
                          <span className="text-xs text-[var(--muted-soft)] mt-0.5 leading-relaxed">
                            {step.detail}
                          </span>
                        )}

                        {/* Dynamic Cycling Thought for Active Phase */}
                        {isActive && !isStreaming && !isComplete && (
                          <div className="flex items-center gap-1.5 mt-1 text-xs text-[var(--body,#3a3a3a)] italic">
                            <span className="text-[var(--brand-teal,#1a3a3a)]">↳</span>
                            <span className="animate-in fade-in duration-300">
                              {currentCyclingThought}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {(isStreaming || isComplete) && (
                <button
                  type="button"
                  onClick={() => setExpanded(false)}
                  className="flex items-center gap-1 mt-2.5 text-xs text-[var(--muted-soft)] hover:text-[var(--ink)] transition-colors cursor-pointer self-start"
                >
                  <IconChevronDown className="h-3 w-3 rotate-180" />
                  <span>Collapse</span>
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
