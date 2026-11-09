import { IconCheck } from "./Icons";

export function Stepper({
  steps,
  current,
}: {
  steps: string[];
  current: number;
}) {
  return (
    <ol className="flex items-start gap-1 sm:gap-2">
      {steps.map((label, i) => {
        const done = i < current;
        const active = i === current;
        const last = i === steps.length - 1;
        return (
          <li key={label} className="relative flex flex-1 flex-col items-center gap-1 sm:gap-1.5">
            <span
              className={`flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-semibold sm:h-7 sm:w-7 sm:text-xs ${
                active
                  ? "bg-[var(--primary)] text-[var(--on-primary)]"
                  : done
                    ? "bg-[var(--success)] text-white"
                    : "border border-[var(--hairline)] bg-[var(--canvas)] text-[var(--muted)]"
              }`}
              aria-current={active ? "step" : undefined}
            >
              {done ? <IconCheck className="h-3 w-3 sm:h-4 sm:w-4" /> : i + 1}
            </span>
            <span className={`max-w-[4rem] text-center text-[10px] sm:max-w-[6rem] sm:text-xs ${active ? "font-medium text-[var(--ink)]" : "text-[var(--text-tertiary)]"}`}>
              {label}
            </span>
            {!last && (
              <span
                aria-hidden="true"
                className={`absolute left-[calc(50%+1rem)] top-3 right-[calc(-50%+1rem)] h-px sm:left-[calc(50%+1.2rem)] sm:right-[calc(-50%+1.2rem)] ${done ? "bg-[var(--success)]" : "bg-[var(--hairline)]"}`}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
