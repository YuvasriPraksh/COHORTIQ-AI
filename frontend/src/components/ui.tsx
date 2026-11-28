import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import type { Resource } from "../hooks/useResource";
import { Icon, type IconName } from "./icons";
import { Notice } from "./Notice";

export function PageHeader({
  title,
  subtitle,
  actions,
  icon,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  icon?: IconName;
}) {
  return (
    <header className="page-header">
      {icon ? <span className="page-header__icon"><Icon name={icon} size={22} /></span> : null}
      <div className="page-header__text">
        <h1 className="page-header__title">{title}</h1>
        {subtitle ? <p className="page-header__subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  );
}

export function Card({ title, actions, children }: { title?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel card" aria-label={title}>
      {title || actions ? (
        <div className="card__head">
          {title ? <h2 className="card__title">{title}</h2> : <span />}
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="blank">
      <p className="blank__title">{title}</p>
      {children ? <p className="blank__text">{children}</p> : null}
      {action}
    </div>
  );
}

/** Loading, error (with retry) and ready states for one API resource. */
export function Loaded<T>({
  resource,
  children,
}: {
  resource: Resource<T> & { reload: () => void };
  children: (data: T) => ReactNode;
}) {
  if (resource.status === "loading") {
    return (
      <div className="skeleton skeleton--block" role="status">
        <span />
        <span />
        <span />
        <span className="visually-hidden">Loading…</span>
      </div>
    );
  }
  if (resource.status === "error") {
    return (
      <Notice
        tone="error"
        title="This couldn't be loaded"
        action={
          <button type="button" className="button button--ghost button--compact" onClick={resource.reload}>
            Retry
          </button>
        }
      >
        {resource.error}
      </Notice>
    );
  }
  return <>{children(resource.data)}</>;
}

export type Tone = "good" | "caution" | "bad" | "neutral" | "info" | "violet";

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

const VERIFICATION: Record<string, { label: string; tone: Tone }> = {
  approved: { label: "Approved", tone: "good" },
  pending: { label: "Pending review", tone: "caution" },
  rejected: { label: "Rejected", tone: "bad" },
};

export function VerificationBadge({ status }: { status: string | null }) {
  const known = VERIFICATION[(status ?? "").toLowerCase()];
  return <Badge tone={known?.tone ?? "neutral"}>{known?.label ?? status ?? "Not set"}</Badge>;
}

/** A button that asks for a second click before doing something consequential. */
export function ConfirmButton({
  label,
  confirmLabel,
  onConfirm,
  disabled,
  variant = "ghost",
}: {
  label: string;
  confirmLabel: string;
  onConfirm: () => void;
  disabled?: boolean;
  variant?: "ghost" | "primary";
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <button
        type="button"
        className={`button button--${variant} button--compact`}
        disabled={disabled}
        onClick={() => setAsking(true)}
      >
        {label}
      </button>
    );
  }
  return (
    <span className="confirm">
      <button
        type="button"
        className="button button--primary button--compact"
        disabled={disabled}
        autoFocus
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </button>
      <button type="button" className="button button--ghost button--compact" onClick={() => setAsking(false)}>
        Keep as is
      </button>
    </span>
  );
}

export function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return "Not recorded";
  // A plain date has no timezone; show it as written.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { dateStyle: "medium" });
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return withTime
    ? date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
    : date.toLocaleDateString(undefined, { dateStyle: "medium" });
}

const PROCESSING: Record<string, { label: string; tone: Tone }> = {
  extracted: { label: "Text extracted", tone: "good" },
  ingested: { label: "Text extracted", tone: "good" },
  processing: { label: "Processing", tone: "info" },
  uploaded: { label: "Uploaded", tone: "info" },
  partial: { label: "Partially extracted", tone: "caution" },
  failed: { label: "Extraction failed", tone: "bad" },
  error: { label: "Extraction failed", tone: "bad" },
};

/** Extraction state recorded by the ingestion workflow. */
export function ProcessingBadge({ status }: { status: string | null }) {
  const known = PROCESSING[(status ?? "").toLowerCase()];
  return <Badge tone={known?.tone ?? "neutral"}>{known?.label ?? status ?? "Unknown"}</Badge>;
}

export function isExtracted(status: string | null): boolean {
  return PROCESSING[(status ?? "").toLowerCase()]?.tone === "good";
}

export function StatCard({
  label,
  value,
  icon,
  tone,
  hint,
}: {
  label: string;
  value: ReactNode;
  icon: IconName;
  tone: "emerald" | "amber" | "rose" | "blue" | "violet" | "teal";
  hint?: ReactNode;
}) {
  return (
    <div className={`stat-card tone-${tone}`}>
      <span className="stat-card__icon"><Icon name={icon} size={20} /></span>
      <div>
        <span className="stat-card__label">{label}</span>
        <strong className="stat-card__value">{value}</strong>
        {hint ? <span className="stat-card__hint">{hint}</span> : null}
      </div>
    </div>
  );
}

/** Side drawer dialog: Escape or the backdrop closes it; focus moves into it on open. */
export function Drawer({
  title,
  subtitle,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, []);
  return (
    <div className="drawer-layer">
      <button type="button" className="drawer-backdrop" aria-label="Close panel" tabIndex={-1} onClick={onClose} />
      <section className={`drawer${wide ? " drawer--wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header className="drawer__head">
          <div>
            <h2 id={titleId} className="drawer__title">{title}</h2>
            {subtitle ? <p className="drawer__subtitle">{subtitle}</p> : null}
          </div>
          <button ref={closeRef} type="button" className="icon-button" aria-label="Close" onClick={onClose}>
            <Icon name="close" />
          </button>
        </header>
        <div className="drawer__body">{children}</div>
      </section>
    </div>
  );
}
