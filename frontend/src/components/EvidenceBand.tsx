import { evidenceBand, type Band } from "@/lib/band";

const TONE: Record<Band, string> = {
  strong: "bg-[var(--accent-legal)]/8 text-[var(--accent-legal)] border border-[var(--accent-legal)]/15",
  moderate: "bg-[var(--accent-primary)]/8 text-[var(--accent-primary)] border border-[var(--accent-primary)]/15",
  weak: "bg-[var(--text-faint)]/8 text-[var(--text-tertiary)] border border-[var(--border-soft)]",
};

export function EvidenceBand({ confidence, label }: { confidence: number; label: string }) {
  const band = evidenceBand(confidence);
  return (
    <span className={`inline-flex items-center rounded-[var(--radius-sm)] px-2 py-0.5 text-[10px] sm:text-xs font-semibold leading-none ${TONE[band]}`}>
      {label}
    </span>
  );
}
