import type { ReactNode } from "react";

export function Chips<T extends string>({
  options,
  value,
  onChange,
  render = (x) => x,
  disabled = false,
}: {
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
  render?: (v: T) => ReactNode;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Filters">
      {options.map((o) => {
        const selected = o === value;
        return (
          <button
            key={o}
            type="button"
            aria-pressed={selected}
            disabled={disabled}
            onClick={() => onChange(o)}
            className={`inline-flex h-10 items-center rounded-[var(--radius-pill)] border px-4 text-sm font-medium transition-all duration-200 ease-[var(--ease-out-cubic)] ${
              selected
                ? "border-[var(--ink)] bg-[var(--surface-strong)] text-[var(--ink)]"
                : "border-[var(--hairline)] bg-[var(--cream-2)] text-[var(--body)] hover:border-[var(--ink)] hover:text-[var(--ink)]"
            }`}
          >
            {render(o)}
          </button>
        );
      })}
    </div>
  );
}
