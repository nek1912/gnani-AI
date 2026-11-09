import { Link, useParams } from "react-router-dom";
import { useI18n } from "@/lib/i18n/provider";
import { getScheme } from "@/lib/data";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Reveal } from "@/components/motion/Reveal";
import { Stagger } from "@/components/motion/Stagger";
import {
  IconChevronRight,
  IconArrowLeft,
  IconLeaf,
  IconBuilding,
  IconRupee,
  IconGift,
  IconCheck,
  IconDoc,
  IconUsers,
  IconShield,
  IconChat,
  IconSparkles,
} from "@/components/ui/Icons";
import { deco } from "@/lib/data/deco";

const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  "crop-insurance": <IconLeaf className="w-4 h-4" />,
  pacs: <IconBuilding className="w-4 h-4" />,
  financial: <IconRupee className="w-4 h-4" />,
  subsidy: <IconGift className="w-4 h-4" />,
};

const CATEGORY_COLORS: Record<string, string> = {
  "crop-insurance": "#bc811e",
  pacs: "#4e99a3",
  financial: "#5691c7",
  subsidy: "#539e55",
};

export default function SchemeDetailPage() {
  const { slug = "" } = useParams<{ slug: string }>();
  const { t, locale } = useI18n();

  const scheme = getScheme(locale, slug);
  const sc = scheme;

  if (!sc) {
    return (
      <div className="min-h-screen px-4 pt-20 pb-24 sm:px-6 md:px-12">
        <EmptyState
          title={t("detail.notFound")}
          action={
            <Link to="/schemes" className="text-sm text-[var(--ink)] underline">
              {t("nav.schemes")}
            </Link>
          }
        />
      </div>
    );
  }

  const catColor = CATEGORY_COLORS[sc.category] ?? "var(--ink)";
  const eligibility = Array.isArray(sc.eligibility) ? sc.eligibility : [];
  const benefits = Array.isArray(sc.benefits) ? sc.benefits : [];
  const howToApply = Array.isArray(sc.howToApply) ? sc.howToApply : [];
  const documents = Array.isArray(sc.documents) ? sc.documents : [];

  return (
    <div className="min-h-screen px-4 pt-10 pb-24 sm:px-6 sm:pt-12 md:px-12">
      {/* ── Back Link ── */}
      <Reveal trigger="load">
        <Link
          to="/schemes"
          className="inline-flex items-center gap-1.5 text-[14px] font-medium text-[var(--muted)] hover:text-[var(--ink)] transition-colors duration-200"
        >
          <IconArrowLeft className="w-4 h-4" />
          {t("nav.schemes")}
        </Link>
      </Reveal>

      {/* ═══════════════════════════════════════════════════════════
          HERO CARD
          ═══════════════════════════════════════════════════════════ */}
      <Reveal trigger="load">
        <div className="relative mt-6 overflow-hidden rounded-[var(--radius-xl)] border border-[var(--hairline)] bg-[var(--cream)]">
          {/* Top color bar */}
          <div className="h-[4px] w-full" style={{ backgroundColor: catColor }} />

          <div className="p-6 md:p-8">
            {/* Category + Status */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span style={{ color: catColor }}>{CATEGORY_ICONS[sc.category]}</span>
                <span className="text-[12px] font-bold uppercase tracking-[0.08em]" style={{ color: catColor }}>
                  {t(`category.${sc.category}`)}
                </span>
              </div>
              <span className="flex items-center gap-1.5 rounded-full bg-[var(--success)]/12 px-3 py-1 text-[11px] font-semibold text-[var(--success)]">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--success)]" />
                {t("schemes.detail.active")}
              </span>
            </div>

            {/* Name + Slug */}
            <h1
              className="mt-4 text-[28px] font-medium leading-[1.15] tracking-[-0.02em] text-[var(--ink)] md:text-[38px]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {sc.name}
            </h1>
            <p className="mt-1 text-[14px] font-medium text-[var(--muted)] uppercase tracking-wider">
              {sc.slug}
            </p>

            {/* Benefit */}
            <p className="mt-4 max-w-2xl text-[16px] leading-[1.7] text-[var(--body)] md:text-[17px]">
              {sc.benefit}
            </p>

            {/* CTAs */}
            <div className="mt-6 flex flex-wrap gap-3">
              <Link to={`/chat?scheme=${sc.slug}&name=${encodeURIComponent(sc.name)}`}>
                <Button
                  variant="dark"
                  size="lg"
                  className="h-12 px-6 text-[15px] gap-2"
                  style={{ color: "white" }}
                >
                  <IconChat className="w-4 h-4" />
                  {t("schemes.detail.askAI")}
                </Button>
              </Link>
            </div>

            {/* Metadata bar */}
            <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-[var(--hairline)] pt-4 text-[13px] text-[var(--muted)]">
              <span className="flex items-center gap-1.5">
                <IconUsers className="w-3.5 h-3.5" />
                {eligibility[0] ?? t("schemes.detail.farmers")}
              </span>
              <span className="flex items-center gap-1.5">
                <IconShield className="w-3.5 h-3.5" />
                {t(`category.${sc.category}`)}
              </span>
              <span className="flex items-center gap-1.5">
                <IconBuilding className="w-3.5 h-3.5" />
                {t("schemes.detail.bankOrPacs")}
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--success)]" />
                {t("schemes.detail.active")}
              </span>
            </div>
          </div>

          {/* Decorative */}
          <div className="pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full bg-[var(--brand-ochre)]/5" />
        </div>
      </Reveal>

      {/* ═══════════════════════════════════════════════════════════
          QUICK OVERVIEW
          ═══════════════════════════════════════════════════════════ */}
      <Reveal trigger="load">
        <div className="mt-10 rounded-[var(--radius-xl)] border border-[var(--hairline)] bg-[var(--surface-elevated)] p-6 md:p-8">
          <p className="text-[11px] font-bold uppercase tracking-[0.1em] text-[var(--muted)]">
            {t("schemes.detail.overview")}
          </p>
          <h2
            className="mt-3 text-[18px] font-semibold text-[var(--ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {t("schemes.detail.whatIsIt")}
          </h2>
          <p
            className="mt-2 text-[15px] leading-[1.75] text-[var(--body)]"
            style={{ fontFamily: "var(--font-answer)" }}
          >
            {sc.overview}
          </p>
        </div>
      </Reveal>

      {/* ═══════════════════════════════════════════════════════════
          WHO CAN APPLY + WHAT DO YOU GET (side by side)
          ═══════════════════════════════════════════════════════════ */}
      <Reveal trigger="load">
        <div className="mt-8 grid gap-5 md:grid-cols-2">
          {/* Who can apply */}
          <div className="rounded-[var(--radius-xl)] border border-[var(--hairline)] bg-[var(--surface-elevated)] p-6 md:p-8">
            <h2
              className="text-[18px] font-semibold text-[var(--ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {t("schemes.detail.whoCanApply")}
            </h2>
            <ul className="mt-4 space-y-3">
              {eligibility.map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--success)]/12">
                    <IconCheck className="w-3 h-3 text-[var(--success)]" />
                  </span>
                  <span className="text-[15px] leading-[1.6] text-[var(--body)]" style={{ fontFamily: "var(--font-answer)" }}>
                    {item}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {/* What do you get */}
          <div className="rounded-[var(--radius-xl)] border border-[var(--hairline)] bg-[var(--surface-elevated)] p-6 md:p-8">
            <h2
              className="text-[18px] font-semibold text-[var(--ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {t("schemes.detail.whatDoYouGet")}
            </h2>
            <ul className="mt-4 space-y-3">
              {benefits.map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full" style={{ backgroundColor: `${catColor}12` }}>
                    <IconShield className="w-3 h-3" />
                  </span>
                  <span className="text-[15px] leading-[1.6] text-[var(--body)]" style={{ fontFamily: "var(--font-answer)" }}>
                    {item}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Reveal>

      {/* ═══════════════════════════════════════════════════════════
          HOW TO APPLY — numbered steps
          ═══════════════════════════════════════════════════════════ */}
      {howToApply.length > 0 && (
        <Reveal trigger="load">
          <div className="mt-10 rounded-[var(--radius-xl)] border border-[var(--hairline)] bg-[var(--surface-elevated)] p-6 md:p-8">
            <h2
              className="text-[18px] font-semibold text-[var(--ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {t("schemes.detail.howToApply")}
            </h2>
            <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {howToApply.map((step, i) => (
                <div key={i} className="relative rounded-[var(--radius-lg)] bg-[var(--cream)] p-5">
                  <span
                    className="text-[28px] font-bold leading-none"
                    style={{ fontFamily: "var(--font-display)", color: catColor }}
                  >
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <p className="mt-2 text-[14px] leading-[1.5] text-[var(--body)]">
                    {step}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </Reveal>
      )}

      {/* ═══════════════════════════════════════════════════════════
          KEY BENEFITS — highlight cards
          ═══════════════════════════════════════════════════════════ */}
      <Reveal trigger="load">
        <div className="mt-8 rounded-[var(--radius-xl)] border border-[var(--hairline)] bg-[var(--surface-elevated)] p-6 md:p-8">
          <h2
            className="text-[18px] font-semibold text-[var(--ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {t("schemes.detail.keyBenefits")}
          </h2>
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {benefits.slice(0, 3).map((b, i) => (
              <div key={i} className="rounded-[var(--radius-lg)] bg-[var(--cream)] p-5 text-center">
                <div className="flex justify-center">
                  <span
                    className="flex h-10 w-10 items-center justify-center rounded-full"
                    style={{ backgroundColor: `${catColor}12`, color: catColor }}
                  >
                    {i === 0 ? <IconShield className="w-5 h-5" /> : i === 1 ? <IconRupee className="w-5 h-5" /> : <IconGift className="w-5 h-5" />}
                  </span>
                </div>
                <p className="mt-3 text-[14px] leading-[1.5] text-[var(--body)]" style={{ fontFamily: "var(--font-answer)" }}>
                  {b}
                </p>
              </div>
            ))}
          </div>
        </div>
      </Reveal>

      {/* ═══════════════════════════════════════════════════════════
          DOCUMENT CHECKLIST
          ═══════════════════════════════════════════════════════════ */}
      {documents.length > 0 && (
        <Reveal trigger="load">
          <div className="mt-8 rounded-[var(--radius-xl)] border border-[var(--hairline)] bg-[var(--surface-elevated)] p-6 md:p-8">
            <h2
              className="text-[18px] font-semibold text-[var(--ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {t("schemes.detail.documentChecklist")}
            </h2>
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              {documents.map((doc, i) => (
                <div key={i} className="flex items-center gap-3 rounded-[var(--radius-md)] bg-[var(--cream)] px-4 py-3">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--success)]/12">
                    <IconCheck className="w-3 h-3 text-[var(--success)]" />
                  </span>
                  <span className="text-[14px] text-[var(--body)]">{doc}</span>
                </div>
              ))}
            </div>
          </div>
        </Reveal>
      )}

      {/* ═══════════════════════════════════════════════════════════
          CTA BANNER
          ═══════════════════════════════════════════════════════════ */}
      <Reveal trigger="load">
        <section className="mt-10 rounded-[var(--radius-xl)] px-8 py-8 text-center" style={{ backgroundColor: catColor }}>
          <h2 className="text-[20px] font-medium text-white md:text-[24px]">
            {t("schemes.detail.haveQuestions").replace("{name}", sc.name)}
          </h2>
          <p className="mt-2 text-[14px] text-white/80">
            {t("schemes.detail.aiHelp")}
          </p>
          <Link
            to={`/chat?scheme=${sc.slug}&name=${encodeURIComponent(sc.name)}`}
            className="mt-5 inline-flex items-center gap-2 rounded-[var(--radius-cta)] bg-white px-5 py-2.5 text-[14px] font-medium transition-all duration-200 hover:bg-white/90 hover:scale-[1.02]"
            style={{ color: catColor }}
          >
            {t("schemes.detail.startConversation")}
            <IconChevronRight className="w-4 h-4" />
          </Link>
        </section>
      </Reveal>
    </div>
  );
}
export { default as SchemeDetailPage } from "./SchemeDetailPage";
