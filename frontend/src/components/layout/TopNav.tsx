import { Link, useLocation } from "react-router-dom";
import { useEffect, useRef } from "react";
import { useAuth, UserButton } from "@clerk/react";
import { useI18n } from "@/lib/i18n/provider";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { HamburgerMenu } from "./HamburgerMenu";

const LEFT_LINKS = [
  { href: "/schemes", key: "nav.schemes" },
  { href: "/services", key: "nav.services" },
  { href: "/legal", key: "nav.legal" },
  { href: "/grievance", key: "nav.grievance" },
] as const;

const RIGHT_LINKS = [
  { href: "/faq", key: "nav.faq" },
] as const;

export function TopNav() {
  const { t } = useI18n();
  const pathname = useLocation().pathname;
  const barRef = useRef<HTMLDivElement>(null);
  const { isSignedIn } = useAuth();

  useEffect(() => {
    let ticking = false;
    const handleScroll = () => {
      if (!ticking) {
        requestAnimationFrame(() => {
          if (barRef.current) {
            const scrollTop = window.scrollY;
            const docHeight = document.documentElement.scrollHeight - window.innerHeight;
            const progress = docHeight > 0 ? scrollTop / docHeight : 0;
            barRef.current.style.transform = `scaleX(${progress})`;
          }
          ticking = false;
        });
        ticking = true;
      }
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const active = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <>
      <div className="h-[72px]" aria-hidden="true" />

      <header className="fixed inset-x-0 top-0 z-30 flex h-[72px] items-center border-b border-[var(--hairline)] bg-[var(--canvas)] px-4 md:px-6 lg:px-8">
        <div
          ref={barRef}
          className="absolute left-0 top-0 h-[2px] w-full origin-left rounded-r-full bg-gradient-to-r from-[var(--ink)] via-[var(--text-primary)] to-[var(--text-secondary)] shadow-[0_0_10px_rgba(10,10,10,0.25)]"
          style={{ transform: "scaleX(0)", willChange: "transform" }}
        />
        <div className="flex w-full items-center justify-between">
          {/* Left: Logo + primary links */}
          <div className="flex items-center gap-1">
            <Link
              to="/"
              className="flex items-center gap-2.5 px-3 py-2"
            >
              <img
                src="/goverment.png"
                alt="JanSahay logo"
                className="h-9 w-9 rounded-full object-cover"
              />
              <span className="text-[18px] font-semibold text-[var(--ink)]">
                JanSahay
              </span>
            </Link>

            <nav className="hidden items-center gap-0.5 pl-2 md:flex" aria-label="Primary">
              {LEFT_LINKS.map((l) => {
                const isActive = active(l.href);
                return (
                  <Link
                    key={l.href}
                    to={l.href}
                    aria-current={isActive ? "page" : undefined}
                    className={`nav-link group relative rounded-full px-3 py-1.5 text-[14px] font-medium transition-colors duration-150 ${
                      isActive
                        ? "text-[var(--ink)]"
                        : "text-[var(--body)] hover:text-[var(--ink)]"
                    }`}
                  >
                    {t(l.key)}
                    <span
                      className={`absolute -bottom-1 left-3 right-3 h-[1px] origin-left scale-x-0 bg-[var(--ink)] transition-transform duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] group-hover:scale-x-100 ${
                        isActive ? "scale-x-100" : ""
                      }`}
                    />
                  </Link>
                );
              })}
            </nav>
          </div>

          {/* Right: Secondary links + Language + CTA */}
          <div className="flex items-center gap-1">
            {RIGHT_LINKS.map((l) => {
              const isActive = active(l.href);
              return (
                <Link
                  key={l.href}
                  to={l.href}
                  aria-current={isActive ? "page" : undefined}
                  className={`nav-link group relative hidden items-center rounded-full px-3 py-1.5 text-[14px] font-medium transition-colors duration-150 md:flex ${
                    isActive
                      ? "text-[var(--ink)]"
                      : "text-[var(--body)] hover:text-[var(--ink)]"
                  }`}
                >
                  {t(l.key)}
                  <span
                    className={`absolute -bottom-1 left-3 right-3 h-[1px] origin-left scale-x-0 bg-[var(--ink)] transition-transform duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] group-hover:scale-x-100 ${
                      isActive ? "scale-x-100" : ""
                    }`}
                  />
                </Link>
              );
            })}

            <LanguageSwitcher />

            <Link
              to="/chat"
              className="hidden h-10 items-center justify-center rounded-full bg-[var(--primary)] px-5 text-[14px] font-semibold text-[var(--on-primary)] transition-colors duration-150 hover:bg-[#1a1a1a] md:inline-flex"
            >
              {t("nav.chat")}
            </Link>

            {isSignedIn ? (
              <UserButton />
            ) : localStorage.getItem("guest_auth_token") ? (
              <div className="hidden items-center gap-2 md:flex">
                <span className="rounded-full border border-[var(--hairline)] bg-[var(--canvas-secondary)] px-3 py-1.5 text-xs font-semibold text-[var(--ink)]">
                  👤 {localStorage.getItem("guest_user_name") || "Guest User"}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    localStorage.removeItem("guest_auth_token");
                    localStorage.removeItem("guest_user_name");
                    window.location.href = "/";
                  }}
                  className="text-xs font-medium text-[var(--muted)] hover:text-[var(--ink)] hover:underline"
                >
                  Sign Out
                </button>
              </div>
            ) : (
              <div className="hidden items-center gap-2 md:flex">
                <button
                  type="button"
                  onClick={() => {
                    localStorage.setItem("guest_auth_token", "guest_demo_user");
                    localStorage.setItem("guest_user_name", "Guest Citizen");
                    window.location.href = "/chat";
                  }}
                  className="h-10 items-center justify-center rounded-full border border-emerald-300 bg-emerald-50 px-4 text-[13px] font-bold text-emerald-800 transition-all hover:bg-emerald-100"
                >
                  ⚡ Guest Access
                </button>
                <Link
                  to="/sign-in"
                  className="h-10 items-center justify-center rounded-full border border-[var(--hairline)] px-4 text-[14px] font-medium text-[var(--ink)] transition-colors duration-150 hover:bg-[var(--canvas-secondary)]"
                >
                  {t("nav.signIn") ?? "Sign In"}
                </Link>
              </div>
            )}



            <HamburgerMenu />
          </div>
        </div>
      </header>
    </>
  );
}
