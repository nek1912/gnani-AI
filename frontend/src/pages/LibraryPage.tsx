import { useMemo, useState } from "react";
import { useI18n } from "@/lib/i18n/provider";
import { getLibraryDocs, libraryDocs as rawLibraryDocs } from "@/lib/data";
import { useTranslatedFields } from "@/lib/useTranslatedFields";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { EmptyState } from "@/components/ui/EmptyState";
import { Reveal } from "@/components/motion/Reveal";
import { Stagger } from "@/components/motion/Stagger";
import { IconDoc, IconChevronRight } from "@/components/ui/Icons";

const domains = ["all", "cropInsurance", "law", "financial", "grievance"] as const;
type Filter = (typeof domains)[number];

export default function LibraryPage() {
  const { t, locale } = useI18n();
  const docs = useMemo(() => getLibraryDocs(locale), [locale]);
  const translated = useTranslatedFields({
    locale,
    items: docs,
    rawItems: rawLibraryDocs as never,
    textFields: ["title", "source"],
    listFields: [],
  });
  const [query, setQuery] = useState("");
  const [domain, setDomain] = useState<Filter>("all");

  const filtered = translated.filter((d) => {
    const okDomain = domain === "all" || d.domain === domain;
    const q = query.trim().toLowerCase();
    const okQuery = !q || d.title.toLowerCase().includes(q) || d.source.toLowerCase().includes(q);
    return okDomain && okQuery;
  });

  return (
    <div className="px-4 pt-8 pb-24 sm:px-6 md:px-12 md:pt-12">
      <Reveal trigger="load">
        <h1 className="text-[24px] font-medium tracking-tight text-[var(--ink)] sm:text-[30px] md:text-[40px]"
            style={{ fontFamily: "var(--font-display)" }}>{t("library.title")}</h1>
        <p className="mt-1 text-[var(--body)]">{t("library.subtitle")}</p>
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("library.searchPlaceholder")} className="mt-4 max-w-sm" />
        <div className="mt-5 flex flex-wrap gap-2">
        {domains.map((d) => (
          <button
            key={d}
            type="button"
            aria-pressed={d === domain}
            onClick={() => setDomain(d)}
            className={`inline-flex h-9 items-center rounded-[var(--radius-md)] border px-3 text-sm font-medium transition-all duration-200 ease-[var(--ease-out-cubic)] sm:h-10 sm:px-4 ${
              d === domain
                ? "border-[var(--surface-dark)] bg-[var(--surface-dark)] text-[var(--on-primary)]"
                : "border-[var(--hairline)] bg-[var(--cream-2)] text-[var(--body)] hover:border-[var(--ink)] hover:text-[var(--ink)]"
            }`}
          >
            {d === "all" ? t("common.all") : d}
          </button>
        ))}
        </div>
      </Reveal>
      {filtered.length === 0 ? (
        <EmptyState title={t("library.empty")} />
      ) : (
        <Stagger as="ul" className="mt-6 space-y-3">
          {filtered.map((d) => (
            <li key={d.id}>
              <a href={d.url} target="_blank" rel="noopener noreferrer" className="block">
                <Card interactive className="flex items-center gap-3">
                  <IconDoc className="w-5 h-5 shrink-0 text-[var(--muted)]" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold text-[var(--ink)]">{d.title}</p>
                    <p className="text-[var(--text-sm)] text-[var(--body)]">
                      {d.source} · {t("library.page", { p: d.page })} · {d.publishedAt}
                    </p>
                  </div>
                  <IconChevronRight className="w-5 h-5 shrink-0 text-[var(--muted)]" />
                </Card>
              </a>
            </li>
          ))}
        </Stagger>
      )}
    </div>
  );
}
export { default as LibraryPage } from "./LibraryPage";
