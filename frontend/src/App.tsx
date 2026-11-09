import { ClerkProvider, useAuth } from "@clerk/react";
import { useEffect } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { LanguageProvider } from "@/lib/i18n/provider";
import { ConditionalNavs } from "@/components/layout/ConditionalNavs";
import { registerTokenProvider } from "@/lib/backend";

import { HomePage } from "@/pages/HomePage";
import { ChatPage } from "@/pages/ChatPage";
import { FaqPage } from "@/pages/FaqPage";
import { GrievancePage } from "@/pages/GrievancePage";
import { GrievanceStatusPage } from "@/pages/GrievanceStatusPage";
import { GrievanceDraftViewPage } from "@/pages/GrievanceDraftViewPage";
import { LegalPage } from "@/pages/LegalPage";
import { LegalDetailPage } from "@/pages/LegalDetailPage";
import { LibraryPage } from "@/pages/LibraryPage";
import { SchemesPage } from "@/pages/SchemesPage";
import { SchemeDetailPage } from "@/pages/SchemeDetailPage";
import { ServicesPage } from "@/pages/ServicesPage";
import { ServiceDetailPage } from "@/pages/ServiceDetailPage";
import SignInPage from "@/pages/SignInPage";
import SignUpPage from "@/pages/SignUpPage";
import NotFoundPage from "@/pages/NotFoundPage";

/**
 * Hands Clerk's session-token getter to the plain-module API layer.
 *
 * The BFF that used to sit in front of FastAPI is gone, so the browser now
 * signs its own requests. api.ts and speech.ts are not components, so they
 * cannot call useAuth() directly; this bridge is what lets them.
 *
 * Must render inside <ClerkProvider>.
 */
function AuthTokenBridge() {
  const { getToken } = useAuth();

  useEffect(() => {
    registerTokenProvider(getToken);
    return () => registerTokenProvider(null);
  }, [getToken]);

  return null;
}

const CLERK_PUBLISHABLE_KEY = import.meta.env
  .VITE_CLERK_PUBLISHABLE_KEY as string | undefined;
const CLERK_SIGN_IN_URL = (import.meta.env.VITE_CLERK_SIGN_IN_URL as
  | string
  | undefined) ?? "/sign-in";
const CLERK_SIGN_UP_URL = (import.meta.env.VITE_CLERK_SIGN_UP_URL as
  | string
  | undefined) ?? "/sign-up";

export default function App() {
  // Fail loudly instead of a blank white page: Vite only exposes VITE_-
  // prefixed vars, so a key kept under the old NEXT_PUBLIC_ name (or missing
  // from .env.local) arrives here as undefined and Clerk would render nothing.
  if (!CLERK_PUBLISHABLE_KEY) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center px-4 text-center">
        <p className="text-[11px] font-bold uppercase tracking-[0.1em] text-[var(--muted)]">
          Configuration error
        </p>
        <h1 className="mt-3 text-[24px] font-medium text-[var(--ink)]">
          Sign-in is not configured
        </h1>
        <p className="mt-3 max-w-md text-[15px] leading-[1.7] text-[var(--body)]">
          VITE_CLERK_PUBLISHABLE_KEY is missing. Copy it from .env.example into
          .env.local and restart `npm run dev`.
        </p>
      </div>
    );
  }

  return (
    <ClerkProvider
      publishableKey={CLERK_PUBLISHABLE_KEY}
      signInUrl={CLERK_SIGN_IN_URL}
      signUpUrl={CLERK_SIGN_UP_URL}
    >
      <BrowserRouter>
        <LanguageProvider>
          <AuthTokenBridge />
          <ConditionalNavs>
            {/* Preserved from app/layout.tsx:94. Targets <main id="content">
                in ConditionalNavs; .skip-link is defined in globals.css. */}
            <a href="#content" className="skip-link">
              Skip to content
            </a>
            <Routes>
              {/* Static segments before dynamic ones. */}
              <Route path="/" element={<HomePage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/faq" element={<FaqPage />} />
              <Route path="/grievance" element={<GrievancePage />} />
              <Route path="/grievance/status" element={<GrievanceStatusPage />} />
              <Route path="/grievance/draft/view" element={<GrievanceDraftViewPage />} />
              <Route path="/legal" element={<LegalPage />} />
              <Route path="/legal/:slug" element={<LegalDetailPage />} />
              <Route path="/library" element={<LibraryPage />} />
              <Route path="/schemes" element={<SchemesPage />} />
              <Route path="/schemes/:slug" element={<SchemeDetailPage />} />
              <Route path="/services" element={<ServicesPage />} />
              <Route path="/services/:slug" element={<ServiceDetailPage />} />
              <Route path="/sign-in/*" element={<SignInPage />} />
              <Route path="/sign-up/*" element={<SignUpPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </ConditionalNavs>
        </LanguageProvider>
      </BrowserRouter>
    </ClerkProvider>
  );
}
