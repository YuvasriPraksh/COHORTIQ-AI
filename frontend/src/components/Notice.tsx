import type { ReactNode } from "react";

type Tone = "info" | "warning" | "error";

const ICONS: Record<Tone, string> = { info: "i", warning: "!", error: "×" };

export function Notice({
  tone = "info",
  title,
  children,
  action,
}: {
  tone?: Tone;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={`notice notice--${tone}`} role={tone === "error" ? "alert" : "status"}>
      <span className="notice__icon" aria-hidden="true">
        {ICONS[tone]}
      </span>
      <div className="notice__body">
        <p className="notice__title">{title}</p>
        {children ? <div className="notice__text">{children}</div> : null}
        {action ? <div className="notice__action">{action}</div> : null}
      </div>
    </div>
  );
}
