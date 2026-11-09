import type { ReactNode } from "react";

type Tone = "neutral" | "success" | "warning" | "error";

const TONES: Record<Tone, string> = {
  neutral: "bg-[var(--cream)] text-[var(--body)] border border-[var(--hairline)]",
  success: "bg-[var(--success)]/12 text-[var(--success)] border border-transparent",
  warning: "bg-[var(--warning)]/14 text-[var(--warning)] border border-transparent",
  error: "bg-[var(--error)]/12 text-[var(--error)] border border-transparent",
};

export function Badge({
  tone = "neutral",
  deco,
  dot = true,
  children,
  className = "",
}: {
  tone?: Tone;
  deco?: string;
  dot?: boolean;
  children: ReactNode;
  className?: string;
}) {
  const style = deco
    ? { backgroundColor: `${deco}1f`, color: deco }
    : undefined;
  return (
    <span
      style={style}
      className={`inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] px-2 py-1 text-[13px] font-medium leading-none ${style ? "" : TONES[tone]} ${className}`}
    >
      {dot ? <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
