import { useState, useRef, useEffect } from "react";
import { LOCALES, type Locale } from "@/lib/i18n/i18n";
import { useI18n } from "@/lib/i18n/provider";

const SHORT: Record<Locale, string> = {
  en: "EN",
  hi: "HI",
  gu: "GU",
  mr: "MR",
  bn: "BN",
  ta: "TA",
  te: "TE",
  kn: "KN",
  pa: "PA",
  or: "OR",
  ml: "ML",
};

export function LanguageSwitcher({ className = "" }: { className?: string }) {
  const { locale, setLocale } = useI18n();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Change language"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex h-8 items-center gap-1.5 rounded-full bg-[var(--accent-tint-soft)] px-3 text-[13px] font-medium text-[var(--body)] transition-colors duration-150 hover:bg-[var(--accent-tint-strong)] hover:text-[var(--ink)]"
      >
        {SHORT[locale]}
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        >
          <path d="M3 4.5L6 7.5L9 4.5" />
        </svg>
      </button>

      {open && (
        <div
          role="listbox"
          aria-label="Language selection"
          className="absolute right-0 top-full z-50 mt-1.5 w-36 overflow-hidden rounded-[14px] border border-[var(--hairline)] bg-white/95 p-1 shadow-[0_8px_30px_rgba(0,0,0,0.1)] backdrop-blur-xl"
        >
          <div className="mb-1 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">
            Language
          </div>
          {LOCALES.map((l) => {
            const isSelected = l === locale;
            return (
              <button
                key={l}
                type="button"
                role="option"
                aria-selected={isSelected}
                onClick={() => {
                  setLocale(l);
                  setOpen(false);
                }}
                className={`flex w-full items-center justify-between rounded-[10px] px-2.5 py-1.5 text-left text-[13px] font-medium transition-colors ${
                  isSelected
                    ? "bg-[var(--accent-tint-strong)] text-[var(--ink)]"
                    : "text-[var(--body)] hover:bg-[var(--accent-tint-soft)]"
                }`}
              >
                <span>{SHORT[l]}</span>
                {isSelected && (
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="var(--primary)" strokeWidth="2">
                    <path d="M3 7l3 3 5-5" />
                  </svg>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
