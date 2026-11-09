
import { useState, useEffect, useCallback } from "react";

interface ArcCarouselItem {
  num: string;
  title: string;
  text: string;
  /** Path to individual illustration (e.g. /images/journey/ask-anything.png) */
  image?: string;
}

export function ArcCarousel({ items }: { items: ArcCarouselItem[] }) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 640);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  const next = useCallback(() => {
    setActiveIndex((prev) => (prev + 1) % items.length);
  }, [items.length]);

  useEffect(() => {
    const timer = setInterval(next, 3000);
    return () => clearInterval(timer);
  }, [next]);

  const getCardStyle = (i: number) => {
    const diff = (i - activeIndex + items.length) % items.length;

    let translateX: number;
    let rotateY: number;
    let scale: number;
    let opacity: number;
    let zIndex: number;

    if (diff === 0) {
      translateX = 0;
      rotateY = 0;
      scale = 1;
      opacity = 1;
      zIndex = 5;
    } else if (diff === 1) {
      translateX = isMobile ? 120 : 200;
      rotateY = -8;
      scale = 0.92;
      opacity = 0.8;
      zIndex = 4;
    } else if (diff === 2) {
      translateX = isMobile ? 200 : 340;
      rotateY = -12;
      scale = 0.84;
      opacity = 0.6;
      zIndex = 3;
    } else if (diff === items.length - 1) {
      translateX = isMobile ? -120 : -200;
      rotateY = 8;
      scale = 0.92;
      opacity = 0.8;
      zIndex = 4;
    } else if (diff === items.length - 2) {
      translateX = isMobile ? -200 : -340;
      rotateY = 12;
      scale = 0.84;
      opacity = 0.6;
      zIndex = 3;
    } else {
      translateX = diff > items.length / 2 ? (isMobile ? -280 : -450) : (isMobile ? 280 : 450);
      rotateY = diff > items.length / 2 ? 15 : -15;
      scale = 0.78;
      opacity = 0;
      zIndex = 0;
    }

    const cardWidth = isMobile ? 220 : 320;
    const cardHeight = isMobile ? 220 : 320;

    return {
      cardWidth,
      cardHeight,
      transform: `translateX(${translateX}px) rotateY(${rotateY}deg) scale(${scale})`,
      opacity,
      zIndex,
      willChange: "transform, opacity" as const,
      border: `1px solid ${diff === 0 ? "rgba(255,255,255,0.6)" : "rgba(255,255,255,0.3)"}`,
      boxShadow:
        diff === 0
          ? "0 25px 50px rgba(0,0,0,0.1)"
          : "0 12px 30px rgba(0,0,0,0.04)",
      transition: "all 0.5s cubic-bezier(0.4, 0, 0.2, 1)",
    };
  };

  if (isMobile) {
    return (
      <div className="flex flex-col items-center">
        {/* Mobile: Simple stacked card layout */}
        <div className="w-full max-w-[300px]">
          {items.map((item, i) => {
            const isActive = i === activeIndex;
            return (
              <div
                key={item.num}
                className={`relative overflow-hidden rounded-[20px] mb-3 transition-all duration-300 ${
                  isActive
                    ? "border border-white/60 shadow-lg opacity-100"
                    : "border border-white/30 opacity-60"
                }`}
                style={{
                  backgroundColor: isActive ? "#dce8dc" : "#f0ebe0",
                }}
                onClick={() => setActiveIndex(i)}
              >
                {/* Illustration layer */}
                {item.image && (
                  <img
                    src={item.image}
                    alt=""
                    aria-hidden="true"
                    className="absolute inset-0 h-full w-full object-cover"
                    style={{
                      objectPosition: "center top",
                      transition: "opacity 0.5s cubic-bezier(0.4, 0, 0.2, 1)",
                      opacity: isActive ? 0.85 : 0.5,
                    }}
                  />
                )}

                {/* Gradient overlay for text readability */}
                <div
                  className="pointer-events-none absolute inset-0"
                  style={{
                    background: isActive
                      ? "linear-gradient(180deg, rgba(220,232,220,0.15) 0%, rgba(196,216,196,0.40) 45%, rgba(196,216,196,0.82) 100%)"
                      : "linear-gradient(180deg, rgba(240,235,224,0.15) 0%, rgba(230,225,212,0.40) 45%, rgba(230,225,212,0.82) 100%)",
                  }}
                />

                {/* Card content */}
                <div className="relative z-10 p-5">
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-black/5">
                    <span className="text-sm font-bold text-[#1a1a2e]/50" style={{ fontFamily: "var(--font-display)" }}>
                      {item.num}
                    </span>
                  </div>
                  <span className="block mt-3 text-[10px] font-semibold tracking-wider text-[#1a1a2e]/40 uppercase" style={{ fontFamily: "var(--font-display)" }}>
                    Step {item.num}
                  </span>
                  <h3 className="mt-1 text-[16px] font-bold tracking-[-0.01em] text-[#1a1a2e]">
                    {item.title}
                  </h3>
                  <p className="mt-1 text-[12px] leading-[1.5] text-[#1a1a2e]/60">
                    {item.text}
                  </p>
                </div>
              </div>
            );
          })}
        </div>

        {/* Navigation dots */}
        <div className="mt-4 flex items-center gap-4">
          <div className="flex gap-2">
            {items.map((_, i) => (
              <button
                key={i}
                onClick={() => setActiveIndex(i)}
                className={`h-2 rounded-full transition-all duration-300 ${
                  i === activeIndex ? "w-8 bg-[#1a1a2e]" : "w-2 bg-[#1a1a2e]/20"
                }`}
                aria-label={`Go to step ${i + 1}`}
              />
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center">
      <div className="relative w-full max-w-[1000px] h-[380px] flex items-center justify-center overflow-hidden">
        {items.map((item, i) => {
          const style = getCardStyle(i);
          const isActive = i === activeIndex;
          return (
            <div
              key={item.num}
              className="absolute rounded-[28px] flex flex-col justify-between cursor-pointer overflow-hidden"
              style={{
                width: `${style.cardWidth}px`,
                height: `${style.cardHeight}px`,
                transform: style.transform,
                opacity: style.opacity,
                zIndex: style.zIndex,
                willChange: style.willChange,
                border: style.border,
                boxShadow: style.boxShadow,
                transition: style.transition,
                backgroundColor: isActive ? "#dce8dc" : "#f0ebe0",
              }}
              onClick={() => setActiveIndex(i)}
            >
              {/* Illustration background layer */}
              {item.image && (
                <img
                  src={item.image}
                  alt=""
                  aria-hidden="true"
                  className="absolute inset-0 h-full w-full"
                  style={{
                    objectFit: "cover",
                    objectPosition: "center top",
                    transition: "opacity 0.5s cubic-bezier(0.4, 0, 0.2, 1)",
                    opacity: isActive ? 1 : 0.6,
                  }}
                />
              )}

              {/* Gradient overlay for text readability — top transparent, bottom stronger */}
              <div
                className="pointer-events-none absolute inset-0 rounded-[28px]"
                style={{
                  background: isActive
                    ? "linear-gradient(180deg, rgba(220,232,220,0.08) 0%, rgba(196,216,196,0.25) 40%, rgba(196,216,196,0.78) 100%)"
                    : "linear-gradient(180deg, rgba(240,235,224,0.08) 0%, rgba(230,225,212,0.25) 40%, rgba(230,225,212,0.78) 100%)",
                  transition: "background 0.5s cubic-bezier(0.4, 0, 0.2, 1)",
                }}
              />

              {/* Number badge — top left */}
              <div className="relative z-10 p-8 pb-0">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-black/5">
                  <span className="text-lg font-bold text-[#1a1a2e]/50" style={{ fontFamily: "var(--font-display)" }}>
                    {item.num}
                  </span>
                </div>
              </div>

              {/* Text content — bottom */}
              <div className="relative z-10 p-8 pt-0">
                <span
                  className="block text-[12px] font-semibold tracking-wider text-[#1a1a2e]/40 uppercase"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  Step {item.num}
                </span>
                <h3 className="mt-2 text-[22px] font-bold tracking-[-0.01em] text-[#1a1a2e]">
                  {item.title}
                </h3>
                <p className="mt-2 text-[14px] leading-[1.6] text-[#1a1a2e]/60 max-w-[250px]">
                  {item.text}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Navigation */}
      <div className="mt-6 flex items-center gap-4">
        <div className="flex gap-2">
          {items.map((_, i) => (
            <button
              key={i}
              onClick={() => setActiveIndex(i)}
              className={`h-2 rounded-full transition-all duration-300 ${
                i === activeIndex ? "w-8 bg-[#1a1a2e]" : "w-2 bg-[#1a1a2e]/20"
              }`}
              aria-label={`Go to step ${i + 1}`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
