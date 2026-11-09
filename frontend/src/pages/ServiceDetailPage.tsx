import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { useI18n } from "@/lib/i18n/provider";
import { getService, getServices } from "@/lib/data";
import { Reveal } from "@/components/motion/Reveal";
import { Card } from "@/components/ui/Card";
import {
  IconRupee,
  IconWarehouse,
  IconShield,
  IconLeaf,
  IconGift,
  IconUsers,
  IconChevronRight,
  IconArrowLeft,
} from "@/components/ui/Icons";

const CATEGORY_META: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
  credit: { icon: <IconRupee className="w-5 h-5" />, color: "#5691c7", label: "Credit" },
  storage: { icon: <IconWarehouse className="w-5 h-5" />, color: "#4e99a3", label: "Storage" },
  insurance: { icon: <IconShield className="w-5 h-5" />, color: "#bc811e", label: "Insurance" },
  "agro-inputs": { icon: <IconLeaf className="w-5 h-5" />, color: "#539e55", label: "Agro services" },
  subsidy: { icon: <IconGift className="w-5 h-5" />, color: "#9b59b6", label: "Subsidy" },
  membership: { icon: <IconUsers className="w-5 h-5" />, color: "#e74c3c", label: "Membership" },
};

export default function ServiceDetailPage() {
  const { slug = "" } = useParams<{ slug: string }>();
  const { t, locale } = useI18n();

  const service = useMemo(() => getService(locale, slug), [locale, slug]);
  const allServices = useMemo(() => getServices(locale), [locale]);

  if (!service) {
    return (
      <div className="px-4 pt-20 pb-24 sm:px-6 md:px-12">
        <div className="text-center">
          <h1 className="text-[24px] font-semibold text-[var(--ink)]">{t("services.detail.notFound")}</h1>
          <Link to="/services" className="mt-4 inline-flex items-center gap-2 text-[var(--brand-teal)] hover:underline">
            <IconArrowLeft className="w-4 h-4" />
            {t("services.detail.backToServices")}
          </Link>
        </div>
      </div>
    );
  }

  const meta = CATEGORY_META[service.category] || CATEGORY_META.membership;
  const whatYouGet = allServices.filter((s) => s.slug !== service.slug).slice(0, 4);

  return (
    <div className="px-4 pt-4 pb-24 sm:px-6 sm:pt-6 md:px-12 md:pt-8">
      {/* Back link */}
      <Reveal trigger="load">
        <Link
          to="/services"
          className="inline-flex items-center gap-1.5 text-[13px] font-medium text-[var(--muted)] hover:text-[var(--ink)] transition-colors duration-200"
        >
          <IconArrowLeft className="w-4 h-4" />
          {t("services.detail.allServices")}
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
                  {service.name}
                </h1>
              </div>
            </div>

            <p className="mt-4 text-[15px] leading-[1.7] text-[var(--body)] max-w-2xl">
              {service.description}
            </p>

            {/* Who it's for — inline chips */}
            <div className="mt-5 flex flex-wrap items-center gap-2">
              <span className="text-[12px] font-semibold uppercase tracking-wider text-[var(--muted)]">{t("services.detail.for")}</span>
              {service.whoCanUse.map((item, i) => (
                <span
                  key={i}
                  className="rounded-[var(--radius-full)] border border-[var(--hairline)] bg-white px-3 py-1 text-[12px] text-[var(--body)]"
                >
                  {item}
                </span>
              ))}
            </div>

            {/* CTA */}
            <div className="mt-6">
              <Link
                to="/chat"
                className="inline-flex items-center gap-2 rounded-[var(--radius-cta)] bg-[var(--ink)] px-5 py-2.5 text-[14px] font-medium text-white transition-all duration-200 hover:bg-[var(--ink)]/90 hover:scale-[1.02]"
              >
                {t("common.askThisScheme") || "Ask about this service"}
                <IconChevronRight className="w-4 h-4" />
              </Link>
            </div>
          </div>

          {/* Right — Quick Facts */}
          <Card className="h-fit lg:sticky lg:top-24">
            <div className="p-5">
              <h3 className="text-[12px] font-semibold uppercase tracking-wider text-[var(--muted)]">
                {t("services.detail.quickFacts")}
              </h3>

              <div className="mt-4 space-y-4">
                {/* ACCESS */}
                <div>
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">{t("services.detail.access")}</span>
                  <p className="mt-1 text-[13px] leading-snug text-[var(--ink)]">
                    {service.howToAccess[0]}
                  </p>
                </div>

                {/* BENEFITS */}
                <div>
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">{t("services.detail.benefits")}</span>
                  <p className="mt-1 text-[13px] leading-snug text-[var(--ink)]">
                    {service.summary}
                  </p>
                </div>

                {/* Source */}
                <div className="pt-3 border-t border-[var(--hairline)]">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">{t("services.detail.source")}</span>
                  <a
                    href={service.source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-1 block text-[12px] text-[var(--brand-teal)] hover:underline"
                  >
                    {service.source.label}
                  </a>
                </div>
              </div>
            </div>
          </Card>
        </section>
      </Reveal>

      {/* ── How to Join ── */}
      <Reveal trigger="load">
        <section className="mt-10">
          <h2
            className="text-[20px] font-medium tracking-tight text-[var(--ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {t("services.detail.howToJoin")}
          </h2>
          <div className="mt-5 flex flex-col gap-3">
            {service.howToAccess.map((step, i) => (
              <div key={i} className="flex items-start gap-4 rounded-[var(--radius-lg)] border border-[var(--hairline)] bg-white p-4">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--brand-teal)] text-[12px] font-semibold text-white">
                  {i + 1}
                </div>
                <p className="flex-1 text-[14px] leading-[1.5] text-[var(--body)] pt-1">
                  {step}
                </p>
              </div>
            ))}
          </div>
        </section>
      </Reveal>

      {/* ── What You Get ── */}
      {whatYouGet.length > 0 && (
        <Reveal trigger="load">
          <section className="mt-10">
            <h2
              className="text-[20px] font-medium tracking-tight text-[var(--ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {t("services.detail.whatYouGet")}
            </h2>
            <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {whatYouGet.map((s) => {
                const sMeta = CATEGORY_META[s.category] || CATEGORY_META.membership;
                return (
                  <Link key={s.slug} to={`/services/${s.slug}`} className="block group">
                    <Card interactive className="h-full">
                      <div className="p-4">
                        <div className="flex items-center gap-2">
                          <span
                            className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-sm)]"
                            style={{ backgroundColor: `${sMeta.color}12`, color: sMeta.color }}
                          >
                            {sMeta.icon}
                          </span>
                          <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: sMeta.color }}>
                            {sMeta.label}
                          </span>
                        </div>
                        <h3 className="mt-2.5 text-[14px] font-semibold text-[var(--ink)] group-hover:text-[var(--brand-teal)] transition-colors duration-200">
                          {s.name}
                        </h3>
                        <p className="mt-1 text-[12px] leading-[1.4] text-[var(--body)] line-clamp-2">
                          {s.summary}
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
        <section className="mt-10 rounded-[var(--radius-xl)] px-8 py-8 text-center" style={{ backgroundColor: meta.color }}>
          <h2 className="text-[20px] font-medium text-white md:text-[24px]">
            {t("services.detail.haveQuestions")}
          </h2>
          <p className="mt-2 text-[14px] text-white/80">
            {t("services.detail.aiHelp")}
          </p>
          <Link
            to="/chat"
            className="mt-5 inline-flex items-center gap-2 rounded-[var(--radius-cta)] bg-white px-5 py-2.5 text-[14px] font-medium transition-all duration-200 hover:bg-white/90 hover:scale-[1.02]"
            style={{ color: meta.color }}
          >
            {t("services.detail.startConversation")}
            <IconChevronRight className="w-4 h-4" />
          </Link>
        </section>
      </Reveal>
    </div>
  );
}
export { default as ServiceDetailPage } from "./ServiceDetailPage";
