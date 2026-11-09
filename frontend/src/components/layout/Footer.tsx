import { Link } from "react-router-dom";
import { useI18n } from "@/lib/i18n/provider";

const COLUMNS = [
  {
    title: "footer.schemes",
    links: [
      { href: "/schemes", key: "nav.schemes" },
      { href: "/services", key: "nav.services" },
    ],
  },
  {
    title: "footer.legal",
    links: [
      { href: "/legal", key: "nav.legal" },
      { href: "/faq", key: "nav.faq" },
      { href: "/grievance", key: "nav.grievance" },
    ],
  },
];

export function Footer() {
  const { t } = useI18n();

  return (
    <footer className="bg-[var(--surface-soft)] border-t border-[var(--hairline)]">
      <div className="mx-auto max-w-[1280px] px-4 py-8 md:px-6 lg:px-8">
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <Link to="/" className="group inline-flex items-center gap-2">
              <img src="/favicon.ico" alt="JanSahay logo" className="h-7 w-7 rounded-full object-cover" />
              <span className="display text-lg text-[var(--ink)]">JanSahay</span>
            </Link>
            <p className="mt-2 text-[13px] leading-relaxed text-[var(--muted)]">
              {t("footer.description")}
            </p>
          </div>
          {COLUMNS.map((col) => (
            <div key={col.title}>
              <h3 className="text-[11px] font-semibold uppercase tracking-[1.5px] text-[var(--muted)]">
                {t(col.title)}
              </h3>
              <ul className="mt-2 space-y-1">
                {col.links.map((link) => (
                  <li key={link.href}>
                    <Link
                      to={link.href}
                      className="text-[13px] text-[var(--body)] hover:text-[var(--ink)] transition-colors"
                    >
                      {t(link.key)}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <div>
            <h3 className="text-[11px] font-semibold uppercase tracking-[1.5px] text-[var(--muted)]">
              {t("footer.contact")}
            </h3>
            <ul className="mt-2 space-y-1">
              <li>
                <Link
                  to="/chat"
                  className="text-[13px] text-[var(--body)] hover:text-[var(--ink)] transition-colors"
                >
                  {t("nav.chat")}
                </Link>
              </li>
              <li className="text-[13px] text-[var(--body)]">
                {t("footer.contactEmail")}
              </li>
              <li className="text-[13px] text-[var(--body)]">
                {t("footer.contactPhone")}
              </li>
            </ul>
          </div>
        </div>
        <div className="mt-6 border-t border-[var(--hairline)] pt-4 text-center text-[12px] text-[var(--muted-soft)]">
          &copy; 2026 JanSahay. Built for Indian cooperatives.
        </div>
      </div>
    </footer>
  );
}
