import { Link } from "react-router-dom";
import { Button } from "@/components/ui/Button";

export default function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4 text-center">
      <p className="text-[11px] font-bold uppercase tracking-[0.1em] text-[var(--muted)]">
        404
      </p>
      <h1
        className="mt-3 text-[28px] font-medium tracking-[-0.02em] text-[var(--ink)] md:text-[38px]"
        style={{ fontFamily: "var(--font-display)" }}
      >
        This page does not exist
      </h1>
      <p className="mt-3 max-w-md text-[15px] leading-[1.7] text-[var(--body)]">
        The link you followed may be broken, or the page may have moved.
      </p>
      <Link to="/" className="mt-6">
        <Button variant="dark" size="lg">
          Back to home
        </Button>
      </Link>
    </div>
  );
}
