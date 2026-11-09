import type { ReactNode } from "react";

type Fill = "canvas" | "cream" | "brand-pink" | "brand-teal" | "brand-lavender" | "brand-peach" | "brand-ochre";

const FILL_STYLES: Record<Fill, string> = {
  canvas: "bg-[var(--canvas)] border border-[var(--hairline)]",
  cream: "bg-[var(--cream-2)] border border-[var(--cream-2)]",
  "brand-pink": "bg-[var(--brand-pink)] text-[var(--brand-pink-text)]",
  "brand-teal": "bg-[var(--brand-teal)] text-[var(--brand-teal-text)]",
  "brand-lavender": "bg-[var(--brand-lavender)] text-[var(--brand-lavender-text)]",
  "brand-peach": "bg-[var(--brand-peach)] text-[var(--brand-peach-text)]",
  "brand-ochre": "bg-[var(--brand-ochre)] text-[var(--brand-ochre-text)]",
};

const isBrandFill = (fill: Fill) => fill.startsWith("brand-");

export function Card({
  children,
  className = "",
  interactive = false,
  fill = "canvas",
}: {
  children: ReactNode;
  className?: string;
  interactive?: boolean;
  fill?: Fill;
}) {
  const brand = isBrandFill(fill);
  const radius = brand ? "rounded-[var(--radius-xl)]" : "rounded-[var(--radius-lg)]";
  const padding = brand ? "p-8" : "p-6";
  const base = FILL_STYLES[fill];
  return (
    <div
      className={`${radius} ${padding} ${base} ${
        interactive && !brand
          ? "transition-all duration-[250ms] ease-[var(--ease-out-cubic)] hover:border-[var(--border-hover)] hover:bg-[var(--cream)] hover:-translate-y-0.5"
          : ""
      } ${className}`}
    >
      {children}
    </div>
  );
}
