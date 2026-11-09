import { Link } from "react-router-dom";
import { useI18n } from "@/lib/i18n/provider";
import { Button } from "@/components/ui/Button";
import { Reveal } from "@/components/motion/Reveal";
import { Stagger } from "@/components/motion/Stagger";
import {
  schemes as rawSchemes,
  services as rawServices,
} from "@/lib/data";
import {
  IconGlobe,
  IconDoc,
  IconMic,
  IconShield,
  IconChevronRight,
  IconSparkles,
  IconChat,
} from "@/components/ui/Icons";
import { Marquee } from "@/components/ui/Marquee";
import { CountUp } from "@/components/ui/CountUp";
import { ArcCarousel } from "@/components/ui/ArcCarousel";

const REVIEWS = [
  {
    name: "Priya Sharma",
    role: "PACS Member, Gujarat",
    body: "JanSahay helped me understand my rights under the cooperative society rules. The multilingual support was a game changer.",
  },
  {
    name: "Rajesh Kumar",
    role: "Farmer, Maharashtra",
    body: "I filed a grievance about PMFBY claim delay through this platform. The step-by-step guidance made it so easy.",
  },
  {
    name: "Ananya Das",
    role: "SHG Leader, West Bengal",
    body: "The schemes section helped me discover benefits I didn't know existed. Now my entire group uses this assistant.",
  },
  {
    name: "Mohammed Irfan",
    role: "Cooperative Secretary, Karnataka",
    body: "Finally a tool that explains legal provisions in simple language. I recommend it to every cooperative member.",
  },
  {
    name: "Lakshmi Nair",
    role: "Dairy Farmer, Kerala",
    body: "Voice support in Malayalam meant my mother could use it too. This is what inclusive governance looks like.",
  },
];

const HOW_STEPS = [
  {
    num: "01",
    title: "landing.how1title",
    text: "landing.how1text",
    image: "/images/journey/ask-anything.png",
  },
  {
    num: "02",
    title: "landing.how2title",
    text: "landing.how2text",
    image: "/images/journey/get-answers.png",
  },
  {
    num: "03",
    title: "landing.how3title",
    text: "landing.how3text",
    image: "/images/journey/verify-details.png",
  },
  {
    num: "04",
    title: "landing.how4title",
    text: "landing.how4text",
    image: "/images/journey/take-action.png",
  },
  {
    num: "05",
    title: "landing.how5title",
    text: "landing.how5text",
    image: "/images/journey/get-closure.png",
  },
];

export default function HomePage() {
  const { t } = useI18n();

  const BENTO_CARDS = [
    {
      icon: <IconGlobe className="w-7 h-7" />,
      title: t("landing.bento1title"),
      text: t("landing.bento1text"),
    },
    {
      icon: <IconDoc className="w-7 h-7" />,
      title: t("landing.bento2title"),
      text: t("landing.bento2text"),
    },
    {
      icon: <IconMic className="w-7 h-7" />,
      title: t("landing.bento3title"),
      text: t("landing.bento3text"),
    },
    {
      icon: <IconShield className="w-7 h-7" />,
      title: t("landing.bento4title"),
      text: t("landing.bento4text"),
    },
    {
      icon: <IconSparkles className="w-7 h-7" />,
      title: t("landing.bento5title"),
      text: t("landing.bento5text"),
    },
    {
      icon: <IconChat className="w-7 h-7" />,
      title: t("landing.bento6title"),
      text: t("landing.bento6text"),
    },
  ];

  const stats = [
    { n: rawSchemes.length, label: t("nav.schemes") },
    { n: rawServices.length, label: t("nav.services") },
    { n: 14, label: t("nav.faq") },
    { n: 13, label: t("landing.trust4") },
    { n: 11, label: t("landing.trust3") },
    { n: 16, label: t("nav.grievance") },
    { n: 6, label: t("landing.trust1") },
  ];

  return (
    <div>
      {/* ── Section 1: Hero — Full Width Background Image with Left Text ── */}
      <section className="relative min-h-[85vh] overflow-hidden rounded-b-[var(--radius-xl)] md:min-h-[70vh]">
        {/* Background Image */}
        <img
          src="/ChatGPT Image Sep 14, 2026, 02_58_06 PM.png"
          alt=""
          aria-hidden="true"
          className="absolute inset-0 h-full w-full object-cover"
        />

        {/* Content — Left Aligned */}
        <div className="relative z-10 flex min-h-[85vh] items-center py-12 sm:py-16 md:min-h-[70vh] md:py-24">
          <div className="w-full max-w-[1200px] px-4 sm:px-6 md:px-12 mx-auto">
            <Reveal trigger="load">
              <div className="flex max-w-3xl flex-col">
                {/* Badge */}
                <span className="inline-flex w-fit items-center gap-1 rounded-full border border-[var(--hairline)] bg-white/60 px-4 py-1.5 text-[12px] font-semibold uppercase tracking-[0.08em] text-[var(--ink)] backdrop-blur-sm">
                  <span className="h-1.5 w-1.5 rounded-full bg-[var(--brand-teal)]" />
                  {t("landing.badge")}
                </span>

                {/* Headline */}
                <h1
                  className="mt-4 text-[28px] font-medium leading-[1.05] tracking-[-0.03em] text-[var(--ink)] sm:text-[40px] md:text-[60px]"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {t("landing.tagline")}
                </h1>

                {/* Subheadline */}
                <p className="mt-6 max-w-4xl text-[16px] leading-[1.65] text-[var(--body)] md:text-[18px]">
                  {t("landing.f1text")}
                </p>

                {/* CTA Row */}
                <div className="mt-8 flex flex-wrap items-center gap-3 sm:mt-10 sm:gap-4">
                  <Link to="/chat">
                    <Button size="lg" className="h-11 gap-2 px-6 text-[15px] font-light !text-white bg-black/80 sm:h-14 sm:px-8 sm:text-[17px]">
                      {t("landing.ctaChat")}
                    </Button>
                  </Link>
                  <Link to="/schemes">
                    <Button size="lg" variant="secondary" className="h-11 px-6 text-[15px] bg-white/80 sm:h-14 sm:px-8 sm:text-[17px]">
                      {t("landing.ctaSchemes")}
                    </Button>
                  </Link>
                </div>

                {/* Trust Badges */}
                <div className="cursor-pointer mt-8 grid max-w-3xl grid-cols-2 gap-2 sm:mt-10 sm:grid-cols-4 sm:gap-3">
                  {[
                    { icon: <IconShield className="w-4 h-4" />, title: t("landing.trust1") },
                    { icon: <IconSparkles className="w-4 h-4" />, title: t("landing.trust2") },
                    { icon: <IconGlobe className="w-4 h-4" />, title: t("landing.trust3") },
                    { icon: <IconDoc className="w-4 h-4" />, title: t("landing.trust4") },
                  ].map((item) => (
                    <div
                      key={item.title}
                      className="flex items-center gap-2.5 rounded-[var(--radius-md)] border border-[var(--hairline)] bg-white/30 px-3.5 py-2.5 backdrop-blur-sm"
                    >
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--brand-teal)]/10 text-[var(--brand-teal)]">
                        {item.icon}
                      </span>
                      <span className="text-[13px] font-medium leading-tight text-[var(--ink)]">
                        {item.title}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

        {/* ── Section 2: Capabilities Marquee ── */}
        <section className="mt-6 px-4 sm:mt-8 sm:px-6 md:px-12">
        <Reveal>
          <p className="eyebrow">{t("landing.trustTitle")}</p>
          <h2
            className="mt-3 text-[30px] font-medium tracking-tight text-[var(--ink)] md:text-[40px]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {t("landing.bentoTitle")}
          </h2>
          <p className="mt-3 max-w-xl text-[var(--body)]">
            {t("landing.bentoSubtitle")}
          </p>
        </Reveal>

        <div className="mt-10">
          <Marquee duration={35}>
            {BENTO_CARDS.map((card) => (
              <div
                key={card.title}
                style={{ touchAction: "manipulation" }}
                className="flex w-[280px] shrink-0 cursor-pointer select-none flex-col justify-between rounded-[var(--radius-xl)] border border-[#e6d5a8] bg-[#FFEDB9] p-6 text-[#1a1a2e] transition-all duration-300 active:scale-95 active:rotate-[1.7deg] sm:w-[380px] sm:p-8"
              >
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-black/5 text-[#1a1a2e]">
                  {card.icon}
                </div>
                <div className="mt-auto pt-6">
                  <h3 className="text-[20px] font-bold leading-snug tracking-[-0.01em] md:text-[22px]">
                    {card.title}
                  </h3>
                  <p className="mt-2 text-[15px] leading-[1.6] text-black/60">
                    {card.text}
                  </p>
                </div>
              </div>
            ))}
          </Marquee>
        </div>
      </section>

      {/* ── Section 3: Stats — Horizontal Ribbon ── */}
      <Reveal className="mt-16 rounded-[var(--radius-xl)] bg-[var(--surface-soft)] sm:mt-24">
        <div className="flex flex-wrap items-center justify-center gap-4 px-4 py-8 sm:gap-8 sm:px-6 sm:py-12 md:gap-16 md:px-12 md:py-14">
          {stats.map((s, i) => (
            <div key={s.label} className="flex items-center gap-4 sm:gap-8 md:gap-16">
              <div className="text-center">
                <p
                  className="text-[32px] font-medium leading-tight tracking-tight text-[var(--ink)] sm:text-[40px] md:text-[56px]"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  <CountUp target={s.n} />
                </p>
                <p className="mt-1 text-[13px] font-medium text-[var(--muted)]">
                  {s.label}
                </p>
              </div>
              {i < stats.length - 1 && (
                <div className="hidden h-12 w-px bg-[var(--hairline)] md:block" />
              )}
            </div>
          ))}
        </div>
      </Reveal>

      {/* ── Section 4: How It Works — Arc Carousel ── */}
      <section className="mt-16 px-4 sm:mt-24 sm:px-6 md:px-12">
        <Reveal className="text-center">
          <p className="eyebrow">{t("landing.trustTitle")}</p>
          <h2
            className="mt-3 text-[30px] font-medium tracking-tight text-[var(--ink)] md:text-[40px]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {t("landing.howTitle")}
          </h2>
        </Reveal>

        <div className="mt-8">
          <ArcCarousel
            items={HOW_STEPS.map((step) => ({
              num: step.num,
              title: t(step.title),
              text: t(step.text),
              image: step.image,
            }))}
          />
        </div>
      </section>

      {/* ── Reviews Marquee ── */}
      <section className="mt-16 mb-16 px-4 sm:mt-24 sm:mb-24 sm:px-6 md:px-12">
        <Reveal>
          <p className="eyebrow">{t("landing.trustTitle")}</p>
          <h2
            className="mt-3 text-[30px] font-medium tracking-tight text-[var(--ink)] md:text-[40px]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {t("landing.reviewsTitle")}
          </h2>
        </Reveal>

        <div className="mt-10">
          <Marquee duration={35}>
            {REVIEWS.map((review) => (
              <div
                key={review.name}
                className="flex w-[260px] shrink-0 cursor-pointer flex-col gap-3 rounded-[var(--radius-xl)] border border-[var(--hairline)] bg-[var(--surface-card)] p-5 transition-colors duration-200 hover:bg-[var(--surface-soft)] sm:w-[300px] sm:p-6"
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--brand-teal)] text-[14px] font-semibold text-white">
                    {review.name.charAt(0)}
                  </div>
                  <div>
                    <p className="text-[14px] font-semibold text-[var(--ink)]">
                      {review.name}
                    </p>
                    <p className="text-[12px] text-[var(--muted)]">
                      {review.role}
                    </p>
                  </div>
                </div>
                <p className="text-[14px] leading-relaxed text-[var(--body)]">
                  &ldquo;{review.body}&rdquo;
                </p>
              </div>
            ))}
          </Marquee>
        </div>
      </section>

    </div>
  );
}
export { default as HomePage } from "./HomePage";
