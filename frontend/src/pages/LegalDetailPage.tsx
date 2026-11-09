import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { useI18n } from "@/lib/i18n/provider";
import { getLegalDoc, getLegalDocs } from "@/lib/data";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Reveal } from "@/components/motion/Reveal";
import { Stagger } from "@/components/motion/Stagger";
import {
  IconScale,
  IconDoc,
  IconShield,
  IconChevronRight,
  IconArrowLeft,
} from "@/components/ui/Icons";
import { formatLegalQuestion } from "@/lib/i18n/formatQuery";

const CATEGORY_META: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
  act: { icon: <IconScale className="w-5 h-5" />, color: "#7989e7", label: "Act" },
  "bye-laws": { icon: <IconDoc className="w-5 h-5" />, color: "#d163a7", label: "Bye-Laws" },
  provisions: { icon: <IconShield className="w-5 h-5" />, color: "#bc811e", label: "Provisions" },
};

const SECTIONS = ["keyProvisions", "applicability", "byLaws"] as const;

export default function LegalDetailPage() {
  const { slug = "" } = useParams<{ slug: string }>();
  const { t, locale } = useI18n();

  const doc = useMemo(() => getLegalDoc(locale, slug), [locale, slug]);
  const sc = doc;

  const allDocs = useMemo(() => getLegalDocs(locale), [locale]);

  if (!sc) {
    return (
      <div className="px-4 pt-20 pb-24 sm:px-6 md:px-12">
        <div className="text-center">
          <h1 className="text-[24px] font-semibold text-[var(--ink)]">{t("legal.detail.notFound")}</h1>
          <Link to="/legal" className="mt-4 inline-flex items-center gap-2 text-[#3b4a8a] hover:underline">
            <IconArrowLeft className="w-4 h-4" />
            {t("legal.detail.backToLegal")}
          </Link>
        </div>
      </div>
    );
  }

  const meta = CATEGORY_META[sc.category] || CATEGORY_META.act;

  const relatedDocs = allDocs.filter((d) => d.slug !== sc.slug && d.category === sc.category).slice(0, 4);
  if (relatedDocs.length < 3) {
    const extras = allDocs.filter((d) => d.slug !== sc.slug && d.category !== sc.category);
    relatedDocs.push(...extras.slice(0, 3 - relatedDocs.length));
  }

  return (
    <div className="px-4 pt-4 pb-24 sm:px-6 sm:pt-6 md:px-12 md:pt-8">
      {/* Back link */}
      <Reveal trigger="load">
        <Link
          to="/legal"
          className="inline-flex items-center gap-1.5 text-[13px] font-medium text-[var(--muted)] hover:text-[var(--ink)] transition-colors duration-200"
        >
          <IconArrowLeft className="w-4 h-4" />
          {t("legal.detail.allLegal")}
        </Link>
      </Reveal>

      {/* ── Hero + Quick Facts ── */}
      <Reveal trigger="load">
        <section className="mt-5 grid gap-6 lg:grid-cols-[1fr_300px]">
          {/* Left — Hero */}
          <div className="rounded-[var(--radius-xl)] bg-[var(--surface-soft)] p-6 md:p-8">
            <div className="flex items-start gap-4">
              <span
                className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[var(--radius-lg)]"
                style={{ backgroundColor: `${meta.color}15`, color: meta.color }}
              >
                {meta.icon}
              </span>
              <div className="flex-1">
                <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: meta.color }}>
                  {meta.label}
                </span>
                <h1
                  className="mt-1 text-[28px] font-medium leading-[1.15] tracking-[-0.02em] text-[var(--ink)] md:text-[34px]"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {sc.title}
                </h1>
              </div>
            </div>

            <p className="mt-4 text-[15px] leading-[1.7] text-[var(--body)] max-w-2xl">
              {sc.overview}
            </p>

            {/* CTA */}
            <div className="mt-6">
              <Link
                to={`/chat?q=${encodeURIComponent(formatLegalQuestion(sc.title, locale))}`}
                className="inline-flex items-center gap-2 rounded-[var(--radius-cta)] bg-[var(--ink)] px-5 py-2.5 text-[14px] font-medium text-white transition-all duration-200 hover:bg-[var(--ink)]/90 hover:scale-[1.02]"
              >
                {t("legal.askThisLaw") || "Ask about this law"}
                <IconChevronRight className="w-4 h-4" />
              </Link>
            </div>
          </div>

          {/* Right — Quick Facts */}
          <Card className="h-fit lg:sticky lg:top-24">
            <div className="p-5">
              <h3 className="text-[12px] font-semibold uppercase tracking-wider text-[var(--muted)]">
                {t("legal.detail.quickFacts")}
              </h3>

              <div className="mt-4 space-y-4">
                {/* Category */}
                <div>
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">{t("legal.detail.type")}</span>
                  <div className="mt-1 flex items-center gap-2">
                    <span
                      className="flex h-5 w-5 items-center justify-center rounded-[var(--radius-sm)]"
                      style={{ backgroundColor: `${meta.color}14`, color: meta.color }}
                    >
                      {meta.icon}
                    </span>
                    <span className="text-[13px] font-medium text-[var(--ink)]">{meta.label}</span>
                  </div>
                </div>

                {/* Key Provisions count */}
                <div>
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">{t("legal.detail.keyProvisions")}</span>
                  <p className="mt-1 text-[13px] leading-snug text-[var(--ink)]">
                    {t("legal.detail.provisionCount").replace("{n}", sc.keyProvisions.length.toString())}
                  </p>
                </div>

                {/* Applicability */}
                {sc.applicability.length > 0 && (
                  <div>
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">{t("legal.detail.applicability")}</span>
                    <p className="mt-1 text-[13px] leading-snug text-[var(--ink)]">
                      {sc.applicability[0]}
                    </p>
                  </div>
                )}

                {/* Source */}
                <div className="pt-3 border-t border-[var(--hairline)]">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">{t("legal.detail.source")}</span>
                  <a
                    href={sc.source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-1 block text-[12px] text-[#3b4a8a] hover:underline"
                  >
                    {sc.source.label}
                  </a>
                </div>
              </div>
            </div>
          </Card>
        </section>
      </Reveal>

      {/* ── Sections: Key Provisions, Applicability, By-Laws ── */}
      <Stagger className="mt-10 space-y-6">
        {SECTIONS.map((s) => (
          <section key={s} className="rounded-[var(--radius-xl)] border border-[var(--hairline)] bg-[var(--surface-elevated)] p-[var(--space-6)]">
            <h2 className="text-[18px] font-semibold text-[var(--ink)]" style={{ fontFamily: "var(--font-display)" }}>
              {t(`legal.${s}`)}
            </h2>
            <ul className="mt-3 space-y-2">
              {sc[s].map((item, i) => (
                <li key={i} className="flex items-start gap-3 rounded-[var(--radius-md)] bg-white/60 px-4 py-3">
                  <span
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold text-white mt-0.5"
                    style={{ backgroundColor: meta.color }}
                  >
                    {i + 1}
                  </span>
                  <span className="text-[14px] leading-[1.6] text-[var(--body)]">{item}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </Stagger>

      {/* ── Related Documents ── */}
      {relatedDocs.length > 0 && (
        <Reveal trigger="load">
          <section className="mt-10">
            <h2
              className="text-[20px] font-medium tracking-tight text-[var(--ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {t("legal.detail.relatedDocs")}
            </h2>
            <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {relatedDocs.map((d) => {
                const dMeta = CATEGORY_META[d.category] || CATEGORY_META.act;
                return (
                  <Link key={d.slug} to={`/legal/${d.slug}`} className="block group">
                    <Card interactive className="h-full">
                      <div className="p-4">
                        <div className="flex items-center gap-2">
                          <span
                            className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-sm)]"
                            style={{ backgroundColor: `${dMeta.color}12`, color: dMeta.color }}
                          >
                            {dMeta.icon}
                          </span>
                          <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: dMeta.color }}>
                            {dMeta.label}
                          </span>
                        </div>
                        <h3 className="mt-2.5 text-[14px] font-semibold text-[var(--ink)] group-hover:text-[#3b4a8a] transition-colors duration-200">
                          {d.badge}
                        </h3>
                        <p className="mt-1 text-[12px] leading-[1.4] text-[var(--body)] line-clamp-2">
                          {d.overview}
                        </p>
                      </div>
                    </Card>
                  </Link>
                );
              })}
            </div>
          </section>
        </Reveal>
      )}

      {/* ── CTA Banner ── */}
      <Reveal trigger="load">
        <section className="mt-10 rounded-[var(--radius-xl)] bg-[#3b4a8a] px-8 py-8 text-center">
          <h2 className="text-[20px] font-medium text-white md:text-[24px]">
            {t("legal.detail.haveQuestions")} {sc.title}?
          </h2>
          <p className="mt-2 text-[14px] text-white/80">
            {t("legal.detail.aiHelp")}
          </p>
          <Link
            to={`/chat?q=${encodeURIComponent(formatLegalQuestion(sc.title, locale))}`}
            className="mt-5 inline-flex items-center gap-2 rounded-[var(--radius-cta)] bg-white px-5 py-2.5 text-[14px] font-medium text-[#3b4a8a] transition-all duration-200 hover:bg-white/90 hover:scale-[1.02]"
          >
            {t("legal.detail.startConversation")}
            <IconChevronRight className="w-4 h-4" />
          </Link>
        </section>
      </Reveal>
    </div>
  );
}
export { default as LegalDetailPage } from "./LegalDetailPage";
