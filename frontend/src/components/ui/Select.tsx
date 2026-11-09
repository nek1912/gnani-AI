import type { SelectHTMLAttributes } from "react";

export function Select({
  className = "",
  invalid = false,
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }) {
  return (
    <select
      {...rest}
      aria-invalid={invalid || undefined}
      className={`h-11 w-full rounded-[var(--radius-cta)] border bg-[var(--canvas)] px-3.5 text-[var(--text-base)] text-[var(--ink)] transition-colors duration-[250ms] disabled:opacity-45 disabled:cursor-not-allowed focus:outline-none ${
        invalid
          ? "border-[var(--state-error)] focus:border-[var(--state-error)]"
          : "border-[var(--border-default)] hover:border-[var(--border-hover)] focus:border-[var(--primary)]"
      } ${className}`}
    >
      {children}
    </select>
  );
}
