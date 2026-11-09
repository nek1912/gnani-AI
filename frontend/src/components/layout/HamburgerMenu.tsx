import { Link } from "react-router-dom";
import { useState, useEffect } from "react";
import { useI18n } from "@/lib/i18n/provider";
import { LanguageSwitcher } from "./LanguageSwitcher";

const LINKS = [
  { href: "/", key: "nav.home" },
  { href: "/schemes", key: "nav.schemes" },
  { href: "/services", key: "nav.services" },
  { href: "/legal", key: "nav.legal" },
  { href: "/faq", key: "nav.faq" },
  { href: "/grievance", key: "nav.grievance" },
] as const;

export function HamburgerMenu() {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex h-8 w-8 items-center justify-center rounded-full text-[var(--body)] transition-colors hover:bg-[var(--accent-tint-soft)] md:hidden"
        aria-label="Open menu"
      >
        <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M3 5h14M3 10h14M3 15h14" />
        </svg>
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-40 bg-[var(--ink)]/30 backdrop-blur-sm"
            aria-hidden="true"
            onClick={() => setOpen(false)}
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Navigation menu"
            className="fixed inset-x-4 top-20 z-50 mx-auto w-full max-w-sm overflow-hidden rounded-[24px] border border-[var(--hairline)] bg-white/95 shadow-[0_8px_40px_rgba(0,0,0,0.12)] backdrop-blur-xl"
          >
            <nav className="flex flex-col p-3" aria-label="Mobile navigation">
              {LINKS.map((l) => (
                <Link
                  key={l.href}
                  to={l.href}
                  onClick={() => setOpen(false)}
                  className="rounded-[14px] px-4 py-2.5 text-[14px] font-medium text-[var(--body)] transition-colors hover:bg-[var(--accent-tint-soft)] hover:text-[var(--ink)]"
                >
                  {t(l.key)}
                </Link>
              ))}
            </nav>

            <div className="border-t border-[var(--hairline)] p-3">
              <div className="flex items-center justify-between gap-3">
                <LanguageSwitcher />
                <Link
                  to="/chat"
                  onClick={() => setOpen(false)}
                  className="flex flex-1 items-center justify-center rounded-full bg-[var(--primary)] px-5 py-2.5 text-[13px] font-semibold text-[var(--on-primary)]"
                >
                  {t("nav.chat")}
                </Link>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
