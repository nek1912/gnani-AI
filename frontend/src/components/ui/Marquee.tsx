
export function Marquee({
  children,
  className = "",
  duration = 30,
}: {
  children: React.ReactNode;
  className?: string;
  duration?: number;
}) {
  return (
    <div
      className={`marquee relative flex overflow-hidden ${className}`}
      style={{
        maskImage:
          "linear-gradient(to right, transparent, black 10%, black 90%, transparent)",
        WebkitMaskImage:
          "linear-gradient(to right, transparent, black 10%, black 90%, transparent)",
      }}
    >
      <div
        className="flex shrink-0 gap-4 marquee-track"
        style={{
          animationDuration: `${duration}s`,
        }}
      >
        {children}
        {children}
      </div>
    </div>
  );
}
