import { useEffect, useRef, type ReactNode, type ElementType } from "react";
import { gsap } from "./gsap";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

/**
 * Fade-up stagger for a container's direct children (cards, list items, steps).
 * The container keeps its own layout classes; its `:scope > *` children animate.
 * Respects prefers-reduced-motion. Transforms are cleared when done.
 */
export function Stagger({
  children,
  className = "",
  y = 14,
  delay = 0,
  stagger = 0.06,
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  y?: number;
  delay?: number;
  stagger?: number;
  as?: ElementType;
}) {
  const ref = useRef<HTMLElement>(null);
  const reduce = usePrefersReducedMotion();

  useEffect(() => {
    const el = ref.current;
    if (!el || reduce) return;
    const items = el.querySelectorAll<HTMLElement>(":scope > *");
    if (!items.length) return;

    const tween = gsap.fromTo(
      items,
      { opacity: 0, y },
      {
        opacity: 1,
        y: 0,
        duration: 0.45,
        delay,
        stagger,
        ease: "power2.out",
        clearProps: "transform",
        scrollTrigger: {
          trigger: el,
          start: "top 85%",
          toggleActions: "play none none reverse",
        },
      },
    );
    return () => {
      tween.scrollTrigger?.kill();
      tween.kill();
      gsap.set(items, { clearProps: "all" });
    };
  }, [reduce, delay, y, stagger]);

  return (
    <Tag ref={ref as never} className={className}>
      {children}
    </Tag>
  );
}
