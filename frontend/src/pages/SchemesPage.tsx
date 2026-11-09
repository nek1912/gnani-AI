import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "@/lib/i18n/provider";
import { getSchemes } from "@/lib/data";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import { Chips } from "@/components/ui/Chips";
import { EmptyState } from "@/components/ui/EmptyState";
import { Reveal } from "@/components/motion/Reveal";
import { Stagger } from "@/components/motion/Stagger";
import { deco } from "@/lib/data/deco";
import {
  IconLeaf,
  IconBuilding,
  IconRupee,
  IconGift,
  IconGrid,
  IconChevronRight,
  IconUsers,
  IconShield,
} from "@/components/ui/Icons";

const CATEGORY_ALL = "all";
const categories = ["all", "crop-insurance", "pacs", "financial", "subsidy"] as const;
type Filter = (typeof categories)[number];

const CATEGORY_META: Record<Filter, { icon: React.ReactNode; color: string; decoKey: string; label: string }> = {
  all: { icon: <IconGrid className="w-4 h-4" />, color: "var(--ink)", decoKey: "teal", label: "All" },
  "crop-insurance": { icon: <IconLeaf className="w-4 h-4" />, color: "#bc811e", decoKey: "gold", label: "Crop insurance" },
  pacs: { icon: <IconBuilding className="w-4 h-4" />, color: "#4e99a3", decoKey: "teal", label: "PACS" },
  financial: { icon: <IconRupee className="w-4 h-4" />, color: "#5691c7", decoKey: "blue", label: "Financial" },
  subsidy: { icon: <IconGift className="w-4 h-4" />, color: "#539e55", decoKey: "green", label: "Subsidy" },
};

export default function SchemesPage() {
  const { t, locale } = useI18n();
  const all = useMemo(() => getSchemes(locale), [locale]);
  const [cat, setCat] = useState<Filter>(CATEGORY_ALL);
  const [query, setQuery] = useState("");

  const filtered = all.filter((s) => {
    const okCat = cat === CATEGORY_ALL || s.category === cat;
    const q = query.trim().toLowerCase();
    const okQuery = !q || s.name.toLowerCase().includes(q) || s.benefit.toLowerCase().includes(q);
    return okCat && okQuery;
  });

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { all: all.length };
    for (const s of all) {
      counts[s.category] = (counts[s.category] ?? 0) + 1;
    }
    return counts;
  }, [all]);

  return (
    <div className="min-h-screen px-4 pt-10 pb-24 sm:px-6 sm:pt-12 md:px-12">
      {/* ── Hero Section ── */}
      <Reveal trigger="load">
        <section className="relative overflow-hidden rounded-[var(--radius-xl)] bg-gradient-to-br from-[#f4debf] via-[#bfb49f] to-[#9c9581] px-6 py-12 md:px-12 md:py-16">
          <div className="relative z-10 flex flex-col gap-10 md:flex-row md:items-center md:gap-16">
            {/* Left — Text */}
            <div className="flex-1">
              <div className="inline-flex items-center gap-2 rounded-[var(--radius-pill)] bg-[var(--brand-ochre)]/10 px-3 py-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--brand-ochre)]" />
                <span className="text-[12px] font-semibold uppercase tracking-[0.1em] text-[var(--brand-ochre)]">
                  {t("nav.schemes")}
                </span>
              </div>
              <h1
                className="mt-5 text-[32px] font-medium leading-[1.1] tracking-[-0.02em] text-[var(--ink)] md:text-[44px]"
                style={{ fontFamily: "var(--font-display)" }}
              >
                {t("schemes.title")}
              </h1>
              <p className="mt-4 max-w-lg text-[16px] leading-relaxed text-[var(--body)] md:text-[18px]">
                {t("schemes.subtitle")}
              </p>

              <div className="mt-8 inline-flex items-center gap-3 rounded-[var(--radius-xl)] border border-[var(--hairline)] bg-white/70 px-5 py-3 backdrop-blur-sm">
                <span className="text-[28px] font-semibold text-[var(--ink)]" style={{ fontFamily: "var(--font-display)" }}>
                  {all.length}
                </span>
                <span className="text-[13px] leading-tight text-[var(--muted)]">
                  {t("schemes.count", { n: "" }).replace(/\d+\s*/, "").trim() || "schemes"}
                </span>
              </div>
            </div>

            {/* Right — Stat Cards */}
            <div className="grid flex-1 grid-cols-1 gap-3 sm:grid-cols-2">
              {categories.filter((c) => c !== "all").map((c) => (
                <button
                  key={c}
                  onClick={() => setCat(c)}
                  className="group flex items-center gap-4 rounded-[var(--radius-lg)] border border-[var(--hairline)] bg-white/70 px-5 py-4 text-left backdrop-blur-sm transition-all duration-200 hover:border-[var(--hairline)] hover:bg-white hover:shadow-sm hover:scale-[1.02] cursor-pointer"
                >
                  <span
                    className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] transition-transform duration-200 group-hover:scale-110"
                    style={{ backgroundColor: `${CATEGORY_META[c].color}12`, color: CATEGORY_META[c].color }}
                  >
                    {CATEGORY_META[c].icon}
                  </span>
                  <div className="flex flex-col">
                    <span className="text-[12px] font-medium uppercase tracking-wide text-[var(--muted)]">
                      {t(`category.${c}`)}
                    </span>
                    <span className="text-[20px] font-semibold text-[var(--ink)]" style={{ fontFamily: "var(--font-display)" }}>
                      {categoryCounts[c] ?? 0}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Decorative shapes */}
          <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-[var(--brand-ochre)]/5" />
          <div className="pointer-events-none absolute -bottom-20 -left-20 h-56 w-56 rounded-full bg-[var(--brand-teal)]/5" />
          <div className="pointer-events-none absolute right-1/3 bottom-6 h-2.5 w-2.5 rounded-full bg-[var(--brand-ochre)]/30" />
        </section>
      </Reveal>

      {/* ── Filters ── */}
      <Reveal trigger="load">
        <div className="mt-8 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <Chips<Filter>
            options={categories}
            value={cat}
            onChange={setCat}
            render={(c) => (
              <span className="flex items-center gap-1.5">
                <span style={{ color: c === cat ? "var(--on-primary)" : CATEGORY_META[c].color }}>{CATEGORY_META[c].icon}</span>
                {c === "all" ? t("common.all") : t(`category.${c}`)}
              </span>
            )}
          />
          <div className="w-full max-w-xs">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("schemes.searchPlaceholder")}
            />
          </div>
        </div>
      </Reveal>

      {/* ── Scheme Grid ── */}
      {filtered.length === 0 ? (
        <div className="mt-10">
          <EmptyState title={t("schemes.empty")} />
        </div>
      ) : (
        <Stagger className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((s) => {
            const meta = CATEGORY_META[s.category];
            const whoCanBenefit = Array.isArray(s.eligibility) && s.eligibility.length > 0 ? s.eligibility[0] : null;
            const keySupport = Array.isArray(s.benefits) && s.benefits.length > 0 ? s.benefits[0] : null;

            return (
              <Link key={s.slug} to={`/schemes/${s.slug}`} className="block group">
                <Card interactive className="relative overflow-hidden h-full flex flex-col">
                  {/* Category color top bar */}
                  <div
                    className="absolute left-0 top-0 h-[3px] w-full"
                    style={{ backgroundColor: meta.color }}
                  />

                  {/* Category label */}
                  <div className="flex items-center gap-2 pt-1">
                    <span style={{ color: meta.color }}>{meta.icon}</span>
                    <span
                      className="text-[11px] font-bold uppercase tracking-[0.08em]"
                      style={{ color: meta.color }}
                    >
                      {t(`category.${s.category}`)}
                    </span>
                  </div>

                  {/* Scheme name */}
                  <h2
                    className="mt-3 text-[18px] font-semibold leading-snug text-[var(--ink)] group-hover:text-[var(--brand-teal)] transition-colors duration-200"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {s.name}
                  </h2>

                  {/* Divider */}
                  <div className="mt-4 h-px bg-[var(--hairline)]" />

                  {/* WHAT IT DOES */}
                  <div className="mt-4">
                    <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-[var(--muted)]">
                      {t("schemes.whatItDoes")}
                    </p>
                    <p className="mt-1.5 text-[14px] leading-[1.6] text-[var(--body)] line-clamp-3">
                      {s.benefit}
                    </p>
                  </div>

                  {/* WHO CAN BENEFIT */}
                  {whoCanBenefit && (
                    <div className="mt-4">
                      <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-[var(--muted)]">
                        {t("schemes.whoCanBenefit")}
                      </p>
                      <div className="mt-1.5 flex items-center gap-2">
                        <IconUsers className="w-4 h-4 shrink-0 text-[var(--muted)]" />
                        <p className="text-[14px] leading-[1.5] text-[var(--body)] line-clamp-1">
                          {whoCanBenefit}
                        </p>
                      </div>
                    </div>
                  )}

                  {/* KEY SUPPORT */}
                  {keySupport && (
                    <div className="mt-4">
                      <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-[var(--muted)]">
                        {t("schemes.keySupport")}
                      </p>
                      <div className="mt-1.5 flex items-center gap-2">
                        <IconShield className="w-4 h-4 shrink-0 text-[var(--muted)]" />
                        <p className="text-[14px] leading-[1.5] text-[var(--body)] line-clamp-1">
                          {keySupport}
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Spacer + CTA */}
                  <div className="mt-auto pt-5">
                    <div className="flex items-center gap-1 text-[13px] font-semibold text-[var(--ink)] group-hover:text-[var(--brand-teal)] transition-colors duration-200">
                      {t("schemes.learnHow")}
                      <IconChevronRight className="w-3.5 h-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
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
export { default as SchemesPage } from "./SchemesPage";
