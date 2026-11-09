import type { ReactNode } from "react";
import { IconInfo, IconAlertTriangle, IconXCircle, IconX } from "./Icons";

type Tone = "info" | "warn" | "error";

const TONES: Record<Tone, string> = {
  info: "bg-[var(--cream)] text-[var(--body)] border-[var(--hairline)]",
  warn: "bg-[var(--warning)]/12 text-[var(--warning)] border-[var(--warning)]/30",
  error: "bg-[var(--error)]/12 text-[var(--error)] border-[var(--error)]/30",
};

const ICONS: Record<Tone, ReactNode> = {
  info: <IconInfo className="h-5 w-5" />,
  warn: <IconAlertTriangle className="h-5 w-5" />,
  error: <IconXCircle className="h-5 w-5" />,
};

export function Alert({
  tone = "info",
  title,
  children,
  onClose,
  closeLabel = "Dismiss",
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
  onClose?: () => void;
  closeLabel?: string;
}) {
  return (
    <div role="alert" className={`flex items-start gap-3 rounded-[var(--radius-md)] border px-4 py-3.5 text-[var(--text-sm)] ${TONES[tone]}`}>
      <span className="mt-0.5 shrink-0">{ICONS[tone]}</span>
      <div className="min-w-0 flex-1">
        {title ? (
          <p className="font-medium leading-tight">{title}</p>
        ) : null}
        <div className={title ? "mt-1 opacity-90" : ""}>{children}</div>
      </div>
      {onClose ? (
        <button
          type="button"
          aria-label={closeLabel}
          onClick={onClose}
          className="ml-2 shrink-0 rounded-[var(--radius-sm)] p-1 opacity-70 transition hover:opacity-100 hover:bg-[var(--cream-2)]"
        >
          <IconX className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}
