import { useEffect, useRef, type ReactNode } from "react";
import { gsap } from "./gsap";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

/**
 * Fade-up reveal for a single block.
 * - `trigger="view"` (default) animates on scroll into view; `"load"` plays
 *   immediately on mount (for above-the-fold content).
 * - Skips animation entirely when the user prefers reduced motion.
 * - Clears transform when done so Tailwind hover transforms keep working.
 */
export function Reveal({
  children,
  className = "",
  y = 16,
  delay = 0,
  trigger = "view",
}: {
  children: ReactNode;
  className?: string;
  y?: number;
  delay?: number;
  trigger?: "load" | "view";
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = usePrefersReducedMotion();

  useEffect(() => {
    const el = ref.current;
    if (!el || reduce) return;

    const vars: gsap.TweenVars = {
      opacity: 0,
      y,
      duration: trigger === "load" ? 0.6 : 0.5,
      delay,
      ease: "power2.out",
      clearProps: "transform",
    };
    const fromVars: gsap.TweenVars = {
      opacity: 1,
      y: 0,
      duration: trigger === "load" ? 0.6 : 0.5,
      delay,
      ease: "power2.out",
      clearProps: "transform",
    };
    if (trigger === "view") {
      fromVars.scrollTrigger = {
        trigger: el,
        start: "top 90%",
        toggleActions: "play none none reverse",
      };
    }

    const tween = gsap.fromTo(el, vars, fromVars);
    return () => {
      tween.scrollTrigger?.kill();
      tween.kill();
    };
  }, [reduce, trigger, delay, y]);

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}
