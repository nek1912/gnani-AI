export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded-[var(--radius-sm)] bg-[var(--cream-2)] ${className}`} aria-hidden="true" />
  );
}
