import { useMemo, useState } from "react";
import { useI18n } from "@/lib/i18n/provider";
import { getFaqItems, faqItems as rawFaqItems } from "@/lib/data";
import { useTranslatedFields } from "@/lib/useTranslatedFields";
import { Input } from "@/components/ui/Input";
import { Chips } from "@/components/ui/Chips";
import { EmptyState } from "@/components/ui/EmptyState";
import { Reveal } from "@/components/motion/Reveal";
import { Stagger } from "@/components/motion/Stagger";
import { Link } from "react-router-dom";
import {
  IconShield,
  IconBuilding,
  IconRupee,
  IconDoc,
  IconScale,
  IconGrid,
  IconChevronRight,
} from "@/components/ui/Icons";

const CATEGORY_ALL = "all";
const categories = ["all", "crop-insurance", "pacs", "financial", "grievance", "legal"] as const;
type Filter = (typeof categories)[number];

const CATEGORY_META: Record<Filter, { icon: React.ReactNode; color: string; label: string }> = {
  all: { icon: <IconGrid className="w-5 h-5" />, color: "var(--ink)", label: "All" },
  "crop-insurance": { icon: <IconShield className="w-5 h-5" />, color: "#bc811e", label: "Crop insurance" },
  pacs: { icon: <IconBuilding className="w-5 h-5" />, color: "#4e99a3", label: "PACS" },
  financial: { icon: <IconRupee className="w-5 h-5" />, color: "#5691c7", label: "Financial" },
  grievance: { icon: <IconDoc className="w-5 h-5" />, color: "#e74c3c", label: "Grievance" },
  legal: { icon: <IconScale className="w-5 h-5" />, color: "#9b59b6", label: "Legal" },
};

export default function FaqPage() {
  const { t, locale } = useI18n();
  const items = useMemo(() => getFaqItems(locale), [locale]);
  const translated = useTranslatedFields({
    locale,
    items,
    rawItems: rawFaqItems as never,
    textFields: ["question", "answer"],
    listFields: [],
  });
  const [query, setQuery] = useState("");
  const [cat, setCat] = useState<Filter>(CATEGORY_ALL);
  const [open, setOpen] = useState<Set<string>>(new Set());

  const filtered = translated.filter((f) => {
    const okCat = cat === CATEGORY_ALL || f.category === cat;
    const q = query.trim().toLowerCase();
    const okQuery = !q || f.question.toLowerCase().includes(q) || f.answer.toLowerCase().includes(q);
    return okCat && okQuery;
  });

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { all: translated.length };
    for (const f of translated) {
      counts[f.category] = (counts[f.category] ?? 0) + 1;
    }
    return counts;
  }, [translated]);

  function toggle(id: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="px-4 pt-4 pb-24 sm:px-6 sm:pt-6 md:px-12 md:pt-8">
      {/* ── Hero Section — Amber FAQ theme ── */}
      <Reveal trigger="load">
        <section className="relative overflow-hidden rounded-[var(--radius-xl)] bg-[#5a4a2a] px-6 py-10 md:px-12 md:py-14">
          <div className="relative z-10 flex flex-col md:flex-row md:items-center md:gap-12">
            {/* Left — Text */}
            <div className="flex-1">
              <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.1em] text-white/60">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--brand-ochre)]" />
                {t("nav.faq")}
              </span>
              <h1
                className="mt-4 text-[32px] font-medium leading-[1.1] tracking-[-0.02em] text-white md:text-[44px]"
                style={{ fontFamily: "var(--font-display)" }}
              >
                {t("faq.title")}
              </h1>
              <p className="mt-4 max-w-lg text-[15px] leading-relaxed text-white/80 md:text-[17px]">
                {t("faq.subtitle")}
              </p>

              {/* Total count */}
              <div className="mt-6 inline-flex items-center gap-2 rounded-[var(--radius-full)] bg-white/15 px-4 py-2 backdrop-blur-sm">
                <span className="text-[22px] font-semibold text-white" style={{ fontFamily: "var(--font-display)" }}>
                  {translated.length}
                </span>
                <span className="text-[13px] text-white/80">
                  {t("faq.count", { n: "" }).replace(/\d+\s*/, "").trim() || "questions"}
                </span>
              </div>
            </div>

            {/* Right — Category Icon Grid */}
            <div className="mt-8 md:mt-0 grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-3 lg:grid-cols-4">
              {categories.filter((c) => c !== "all").map((c) => {
                const meta = CATEGORY_META[c];
                return (
                  <button
                    key={c}
                    onClick={() => setCat(c)}
                    className="group flex flex-col items-center gap-2 rounded-[var(--radius-lg)] bg-white/10 p-4 backdrop-blur-sm transition-all duration-200 hover:bg-white/20 hover:scale-105 cursor-pointer"
                  >
                    <span
                      className="flex h-10 w-10 items-center justify-center rounded-[var(--radius-md)] transition-colors duration-200"
                      style={{ backgroundColor: `${meta.color}30`, color: meta.color }}
                    >
                      {meta.icon}
                    </span>
                    <span className="text-[11px] font-medium text-white/90 text-center leading-tight">
                      {meta.label}
                    </span>
                    <span className="text-[10px] text-white/60">
                      {categoryCounts[c] ?? 0}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Decorative shapes */}
          <div className="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-full border border-white/10" />
          <div className="pointer-events-none absolute -bottom-20 -left-20 h-80 w-80 rounded-full border border-white/10" />
          <div className="pointer-events-none absolute right-1/4 bottom-8 h-3 w-3 rounded-full bg-[var(--brand-ochre)]/40" />
          <div className="pointer-events-none absolute left-1/3 top-12 h-2 w-2 rounded-full bg-white/20" />
        </section>
      </Reveal>

      {/* ── Filters ── */}
      <Reveal trigger="load">
        <div className="mt-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <Chips<Filter>
            options={categories}
            value={cat}
            onChange={setCat}
            render={(c) => (
              <span className="flex items-center gap-1.5">
                <span className="w-4 h-4" style={{ color: CATEGORY_META[c].color }}>{CATEGORY_META[c].icon}</span>
                {c === "all" ? t("common.all") : t(`faqCategory.${c}`)}
              </span>
            )}
          />
          <div className="w-full max-w-xs">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("faq.searchPlaceholder")}
            />
          </div>
        </div>
      </Reveal>

      {/* ── FAQ Accordion ── */}
      {filtered.length === 0 ? (
        <div className="mt-10">
          <EmptyState title={t("faq.empty")} />
        </div>
      ) : (
        <Stagger as="ul" className="mt-6 space-y-3">
          {filtered.map((f) => {
            const isOpen = open.has(f.id);
            const meta = CATEGORY_META[f.category as Filter] || CATEGORY_META.legal;
            return (
              <li
                key={f.id}
                className={`rounded-[var(--radius-lg)] border transition-all duration-200 ${
                  isOpen
                    ? "border-[var(--border-hover)] bg-white shadow-sm"
                    : "border-[var(--hairline)] bg-white hover:border-[var(--border-hover)]"
                }`}
              >
                <button
                  type="button"
                  aria-expanded={isOpen}
                  onClick={() => toggle(f.id)}
                  className="flex w-full items-center gap-4 px-5 py-4 text-left"
                >
                  {/* Category icon */}
                  <span
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)]"
                    style={{ backgroundColor: `${meta.color}12`, color: meta.color }}
                  >
                    {meta.icon}
                  </span>

                  {/* Question */}
                  <span className="flex-1 text-[15px] font-medium text-[var(--ink)]">
                    {f.question}
                  </span>

                  {/* Chevron */}
                  <IconChevronRight
                    className={`h-5 w-5 shrink-0 text-[var(--muted)] transition-transform duration-200 ${
                      isOpen ? "rotate-90" : ""
                    }`}
                  />
                </button>

                {/* Answer */}
                {isOpen && (
                  <div className="px-5 pb-5 pl-17">
                    <div className="border-t border-[var(--hairline)] pt-4">
                      <p className="text-[14px] leading-[1.7] text-[var(--body)]">
                        {f.answer}
                      </p>
                      <Link
                        to={`/chat?q=${encodeURIComponent(f.question)}`}
                        className="mt-4 inline-flex items-center gap-1.5 text-[13px] font-medium text-[var(--brand-teal)] hover:underline"
                      >
                        {t("faq.askInChat")}
                        <IconChevronRight className="w-3.5 h-3.5" />
                      </Link>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </Stagger>
      )}

      {/* ── CTA Banner ── */}
      <Reveal trigger="load">
        <section className="mt-12 rounded-[var(--radius-xl)] bg-[var(--surface-soft)] px-8 py-10 text-center">
          <h2
            className="text-[22px] font-medium tracking-tight text-[var(--ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Still have questions?
          </h2>
          <p className="mt-2 text-[14px] text-[var(--body)]">
            Our AI assistant can help you find answers tailored to your situation.
          </p>
          <Link
            to="/chat"
            className="mt-5 inline-flex items-center gap-2 rounded-[var(--radius-cta)] bg-[var(--ink)] px-5 py-2.5 text-[14px] font-medium text-white transition-all duration-200 hover:bg-[var(--ink)]/90 hover:scale-[1.02]"
          >
            Ask in chat
            <IconChevronRight className="w-4 h-4" />
          </Link>
        </section>
      </Reveal>
    </div>
  );
}
export { default as FaqPage } from "./FaqPage";
