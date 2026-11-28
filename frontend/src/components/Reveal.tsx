import { useEffect, useRef, useState, type CSSProperties, type ElementType, type ReactNode } from "react";

/**
 * Scroll-triggered reveal. Content is fully rendered and readable without
 * JavaScript support for IntersectionObserver; CSS disables the motion when the
 * visitor prefers reduced motion.
 */
export function Reveal({
  children,
  as: Tag = "div",
  delay = 0,
  className = "",
  variant = "up",
}: {
  children: ReactNode;
  as?: ElementType;
  delay?: number;
  className?: string;
  variant?: "up" | "left" | "right" | "zoom";
}) {
  const ref = useRef<HTMLElement | null>(null);
  const [shown, setShown] = useState(() => typeof window === "undefined" || typeof window.IntersectionObserver !== "function");

  useEffect(() => {
    const node = ref.current;
    if (shown || !node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setShown(true);
          observer.disconnect();
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.12 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [shown]);

  return (
    <Tag
      ref={ref}
      className={`reveal reveal--${variant}${shown ? " is-visible" : ""}${className ? ` ${className}` : ""}`}
      style={{ "--reveal-delay": `${delay}ms` } as CSSProperties}
    >
      {children}
    </Tag>
  );
}
