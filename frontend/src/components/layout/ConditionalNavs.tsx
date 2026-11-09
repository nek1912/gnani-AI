import { useLocation } from "react-router-dom";
import { TopNav } from "./TopNav";
import { Footer } from "./Footer";
import { FloatingChatWidget } from "@/components/FloatingChatWidget";

export function ConditionalNavs({ children }: { children: React.ReactNode }) {
  const pathname = useLocation().pathname;
  const isChat = pathname.startsWith("/chat");
  const isAuth = pathname.startsWith("/sign-in") || pathname.startsWith("/sign-up");
  const hideNav = isChat || isAuth;

  return (
    <>
      {!hideNav && <TopNav />}
      <main id="content">{children}</main>
      {!hideNav && <Footer />}
      {!hideNav && <FloatingChatWidget />}
    </>
  );
}
