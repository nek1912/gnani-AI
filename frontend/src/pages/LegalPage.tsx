import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "@/lib/i18n/provider";
import { getLegalDocs } from "@/lib/data";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Chips } from "@/components/ui/Chips";
import { EmptyState } from "@/components/ui/EmptyState";
import { Reveal } from "@/components/motion/Reveal";
import { Stagger } from "@/components/motion/Stagger";
import {
  IconScale,
  IconDoc,
  IconShield,
  IconGrid,
  IconChevronRight,
} from "@/components/ui/Icons";

const CATEGORY_ALL = "all";
const categories = ["all", "act", "bye-laws", "provisions"] as const;
type Filter = (typeof categories)[number];

const CATEGORY_META: Record<Filter, { icon: React.ReactNode; color: string; decoKey: string; label: string }> = {
  all: { icon: <IconGrid className="w-5 h-5" />, color: "var(--ink)", decoKey: "indigo", label: "All" },
  act: { icon: <IconScale className="w-5 h-5" />, color: "#7989e7", decoKey: "indigo", label: "Acts" },
  "bye-laws": { icon: <IconDoc className="w-5 h-5" />, color: "#d163a7", decoKey: "magenta", label: "Bye-Laws" },
  provisions: { icon: <IconShield className="w-5 h-5" />, color: "#bc811e", decoKey: "gold", label: "Provisions" },
};

export default function LegalPage() {
  const { t, locale } = useI18n();
  const all = useMemo(() => getLegalDocs(locale), [locale]);
  const [cat, setCat] = useState<Filter>(CATEGORY_ALL);
  const [query, setQuery] = useState("");

  const filtered = all.filter((d) => {
    const okCat = cat === CATEGORY_ALL || d.category === cat;
    const q = query.trim().toLowerCase();
    const okQuery = !q || d.badge.toLowerCase().includes(q) || d.overview.toLowerCase().includes(q);
    return okCat && okQuery;
  });

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { all: all.length };
    for (const d of all) {
      counts[d.category] = (counts[d.category] ?? 0) + 1;
    }
    return counts;
  }, [all]);

  return (
    <div className="px-4 pt-6 pb-24 sm:px-6 sm:pt-8 md:px-12 md:pt-12">
      {/* ── Hero Section — Indigo legal theme ── */}
      <Reveal trigger="load">
        <section className="relative overflow-hidden rounded-[var(--radius-xl)] bg-[#3b4a8a] px-6 py-10 md:px-12 md:py-14">
          <div className="relative z-10 flex flex-col md:flex-row md:items-center md:gap-12">
            {/* Left — Text */}
            <div className="flex-1">
              <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.1em] text-white/60">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--brand-ochre)]" />
                {t("nav.legal")}
              </span>
              <h1
                className="mt-4 text-[32px] font-medium leading-[1.1] tracking-[-0.02em] text-white md:text-[44px]"
                style={{ fontFamily: "var(--font-display)" }}
              >
                {t("legal.title")}
              </h1>
              <p className="mt-4 max-w-lg text-[15px] leading-relaxed text-white/80 md:text-[17px]">
                {t("legal.subtitle")}
              </p>

              {/* Total count */}
              <div className="mt-6 inline-flex items-center gap-2 rounded-[var(--radius-full)] bg-white/15 px-4 py-2 backdrop-blur-sm">
                <span className="text-[22px] font-semibold text-white" style={{ fontFamily: "var(--font-display)" }}>
                  {all.length}
                </span>
                <span className="text-[13px] text-white/80">
                  {t("legal.count", { n: "" }).replace(/\d+\s*/, "").trim() || "documents"}
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
                      {c === "act" ? t("legal.acts") : c === "bye-laws" ? t("legal.bylaws") : t("legal.provisions")}
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
                {c === "all" ? t("common.all") : t(`legalCategory.${c}`)}
              </span>
            )}
          />
          <div className="w-full max-w-xs">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("legal.searchPlaceholder")}
            />
          </div>
        </div>
      </Reveal>

      {/* ── Legal Document Grid — Unique card style ── */}
      {filtered.length === 0 ? (
        <div className="mt-10">
          <EmptyState title={t("legal.empty")} />
        </div>
      ) : (
        <Stagger className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((d) => {
            const meta = CATEGORY_META[d.category];
            return (
              <Link key={d.slug} to={`/legal/${d.slug}`} className="block group">
                <Card interactive className="relative overflow-hidden h-full">
                  {/* Top color strip */}
                  <div
                    className="absolute left-0 top-0 h-[3px] w-full"
                    style={{ backgroundColor: meta.color }}
                  />

                  <div className="px-5 pt-5 pb-5">
                    {/* Category icon + badge */}
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-2.5">
                        <span
                          className="flex h-9 w-9 items-center justify-center rounded-[var(--radius-md)]"
                          style={{
                            backgroundColor: `${meta.color}14`,
                            color: meta.color,
                          }}
                        >
                          {meta.icon}
                        </span>
                        <div>
                          <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: meta.color }}>
                            {d.category === "act" ? t("legal.acts") : d.category === "bye-laws" ? t("legal.bylaws") : t("legal.provisions")}
                          </span>
                        </div>
                      </div>
                      <span
                        className="inline-block h-2 w-2 rounded-full mt-1.5"
                        style={{ backgroundColor: meta.color }}
                      />
                    </div>

                    {/* Document title */}
                    <h2 className="mt-4 text-[16px] font-semibold leading-snug text-[var(--ink)] group-hover:text-[#3b4a8a] transition-colors duration-200">
                      {d.badge}
                    </h2>

                    {/* Overview — clamp to 3 lines */}
                    <p className="mt-2 text-[13px] leading-[1.6] text-[var(--body)] line-clamp-3">
                      {d.overview}
                    </p>

                    {/* Bottom bar — category + CTA */}
                    <div className="mt-4 flex items-center justify-between border-t border-[var(--border)] pt-3">
                      <span className="text-[11px] font-medium text-[var(--muted)] uppercase tracking-wider">
                        {t(`legalCategory.${d.category}`)}
                      </span>
                      <span className="flex items-center gap-1 text-[12px] font-medium text-[var(--muted)] group-hover:text-[#3b4a8a] transition-colors duration-200">
                        {t("common.askThisScheme") || "Read"}
                        <IconChevronRight className="w-3.5 h-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
                      </span>
                    </div>
                  </div>
                </Card>
              </Link>
            );
          })}
        </Stagger>
      )}
    </div>
  );
}
export { default as LegalPage } from "./LegalPage";
