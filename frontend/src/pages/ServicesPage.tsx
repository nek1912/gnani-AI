import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "@/lib/i18n/provider";
import { getServices } from "@/lib/data";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Chips } from "@/components/ui/Chips";
import { EmptyState } from "@/components/ui/EmptyState";
import { Reveal } from "@/components/motion/Reveal";
import { Stagger } from "@/components/motion/Stagger";
import {
  IconRupee,
  IconWarehouse,
  IconShield,
  IconLeaf,
  IconGift,
  IconUsers,
  IconGrid,
  IconChevronRight,
  IconCheck,
} from "@/components/ui/Icons";

const SERVICE_HOOKS: Record<string, { questionKey: string; benefitKeys: string[] }> = {
  "pacs-membership": {
    questionKey: "serviceHooks.pacs-membership.question",
    benefitKeys: ["serviceHooks.pacs-membership.b0", "serviceHooks.pacs-membership.b1", "serviceHooks.pacs-membership.b2"],
  },
  "short-term-crop-credit": {
    questionKey: "serviceHooks.short-term-crop-credit.question",
    benefitKeys: ["serviceHooks.short-term-crop-credit.b0", "serviceHooks.short-term-crop-credit.b1"],
  },
  "godown-storage": {
    questionKey: "serviceHooks.godown-storage.question",
    benefitKeys: ["serviceHooks.godown-storage.b0", "serviceHooks.godown-storage.b1"],
  },
  "agro-input-supply": {
    questionKey: "serviceHooks.agro-input-supply.question",
    benefitKeys: ["serviceHooks.agro-input-supply.b0", "serviceHooks.agro-input-supply.b1"],
  },
  "pmfby-enrolment": {
    questionKey: "serviceHooks.pmfby-enrolment.question",
    benefitKeys: ["serviceHooks.pmfby-enrolment.b0", "serviceHooks.pmfby-enrolment.b1"],
  },
  "cooperative-subsidy": {
    questionKey: "serviceHooks.cooperative-subsidy.question",
    benefitKeys: ["serviceHooks.cooperative-subsidy.b0", "serviceHooks.cooperative-subsidy.b1"],
  },
  "pm-fb-enrollment": {
    questionKey: "serviceHooks.pm-fb-enrollment.question",
    benefitKeys: ["serviceHooks.pm-fb-enrollment.b0", "serviceHooks.pm-fb-enrollment.b1"],
  },
  "cooperative-training": {
    questionKey: "serviceHooks.cooperative-training.question",
    benefitKeys: ["serviceHooks.cooperative-training.b0", "serviceHooks.cooperative-training.b1"],
  },
  "digital-banking": {
    questionKey: "serviceHooks.digital-banking.question",
    benefitKeys: ["serviceHooks.digital-banking.b0", "serviceHooks.digital-banking.b1"],
  },
};

const CATEGORY_ALL = "all";
const categories = ["all", "credit", "storage", "insurance", "agro-inputs", "subsidy", "membership"] as const;
type Filter = (typeof categories)[number];

const CATEGORY_META: Record<Filter, { icon: React.ReactNode; color: string; decoKey: string; labelKey: string }> = {
  all: { icon: <IconGrid className="w-5 h-5" />, color: "var(--ink)", decoKey: "teal", labelKey: "services.all" },
  credit: { icon: <IconRupee className="w-5 h-5" />, color: "#5691c7", decoKey: "blue", labelKey: "services.credit" },
  storage: { icon: <IconWarehouse className="w-5 h-5" />, color: "#4e99a3", decoKey: "teal", labelKey: "services.storage" },
  insurance: { icon: <IconShield className="w-5 h-5" />, color: "#bc811e", decoKey: "gold", labelKey: "services.insurance" },
  "agro-inputs": { icon: <IconLeaf className="w-5 h-5" />, color: "#539e55", decoKey: "green", labelKey: "services.agroServices" },
  subsidy: { icon: <IconGift className="w-5 h-5" />, color: "#9b59b6", decoKey: "purple", labelKey: "services.subsidy" },
  membership: { icon: <IconUsers className="w-5 h-5" />, color: "#e74c3c", decoKey: "red", labelKey: "services.membership" },
};

export default function ServicesPage() {
  const { t, locale } = useI18n();
  const all = useMemo(() => getServices(locale), [locale]);
  const [cat, setCat] = useState<Filter>(CATEGORY_ALL);
  const [query, setQuery] = useState("");

  const filtered = all.filter((s) => {
    const okCat = cat === CATEGORY_ALL || s.category === cat;
    const q = query.trim().toLowerCase();
    const okQuery = !q || s.name.toLowerCase().includes(q) || s.summary.toLowerCase().includes(q);
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
    <div className="px-4 pt-6 pb-24 sm:px-6 sm:pt-8 md:px-12 md:pt-12">
      {/* ── Hero Section — Two Column with Icon Grid ── */}
      <Reveal trigger="load">
        <section className="relative overflow-hidden rounded-[var(--radius-xl)] bg-[var(--brand-teal)] px-6 py-10 md:px-12 md:py-14">
          <div className="relative z-10 flex flex-col md:flex-row md:items-center md:gap-12">
            {/* Left — Text */}
            <div className="flex-1">
              <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.1em] text-[var(--brand-teal-text)]/70">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--brand-ochre)]" />
                {t("nav.services")}
              </span>
              <h1
                className="mt-4 text-[32px] font-medium leading-[1.1] tracking-[-0.02em] text-[var(--brand-teal-text)] md:text-[44px]"
                style={{ fontFamily: "var(--font-display)" }}
              >
                {t("services.title")}
              </h1>
              <p className="mt-4 max-w-lg text-[15px] leading-relaxed text-[var(--brand-teal-text)]/80 md:text-[17px]">
                {t("services.subtitle")}
              </p>

              {/* Total count */}
              <div className="mt-6 inline-flex items-center gap-2 rounded-[var(--radius-full)] bg-white/15 px-4 py-2 backdrop-blur-sm">
                <span className="text-[22px] font-semibold text-white" style={{ fontFamily: "var(--font-display)" }}>
                  {all.length}
                </span>
                <span className="text-[13px] text-white/80">{t("services.count", { n: "" }).replace(/\d+\s*/, "").trim() || "services"}</span>
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
                      {t(meta.labelKey)}
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
                {c === "all" ? t("common.all") : t(`serviceCategory.${c}`)}
              </span>
            )}
          />
          <div className="w-full max-w-xs">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("services.searchPlaceholder")}
            />
          </div>
        </div>
      </Reveal>

      {/* ── Service Grid ── */}
      {filtered.length === 0 ? (
        <div className="mt-10">
          <EmptyState title={t("services.empty")} />
        </div>
      ) : (
        <Stagger className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((s) => {
            const meta = CATEGORY_META[s.category];
            const hook = SERVICE_HOOKS[s.slug];
            return (
              <Link key={s.slug} to={`/services/${s.slug}`} className="block group">
                <Card interactive className="relative overflow-hidden h-full">
                  {/* Category color accent bar */}
                  <div
                    className="absolute left-0 top-0 h-full w-[3px] rounded-l-[var(--radius-lg)]"
                    style={{ backgroundColor: meta.color }}
                  />

                  <div className="pl-5 pr-5 py-5">
                    {/* Hook question */}
                    {hook && (
                      <div className="flex items-center gap-2">
                        <span
                          className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-sm)]"
                          style={{ backgroundColor: `${meta.color}12`, color: meta.color }}
                        >
                          {meta.icon}
                        </span>
                        <span className="text-[13px] font-medium text-[var(--body)]">
                          {t(hook.questionKey)}
                        </span>
                      </div>
                    )}

                    {/* Service name */}
                    <h2 className="mt-3 text-[18px] font-semibold leading-snug text-[var(--ink)] group-hover:text-[var(--brand-teal)] transition-colors duration-200">
                      {s.name}
                    </h2>

                    {/* Summary */}
                    <p className="mt-1.5 text-[13px] leading-[1.5] text-[var(--body)] line-clamp-2">
                      {s.summary}
                    </p>

                    {/* Benefits with checkmarks */}
                    {hook && (
                      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
                        {hook.benefitKeys.map((key, i) => (
                          <span key={i} className="flex items-center gap-1 text-[12px] text-[var(--body)]">
                            <IconCheck className="w-3.5 h-3.5 text-[var(--brand-teal)]" />
                            {t(key)}
                          </span>
                        ))}
                      </div>
                    )}

                    {/* CTA */}
                    <div className="mt-4 flex items-center gap-1 text-[13px] font-medium text-[var(--brand-teal)] group-hover:text-[var(--ink)] transition-colors duration-200">
                      {t("common.askThisScheme") || "Explore"}
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
export { default as ServicesPage } from "./ServicesPage";
