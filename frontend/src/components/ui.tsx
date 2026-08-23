"use client";

import { AlertCircle, Loader2, RefreshCw } from "lucide-react";
import {
  buttonClass,
  type ButtonSize,
  type ButtonVariant,
} from "@/components/button-styles";

// Re-exported so client components can pull the whole primitive set from
// one place; Server Components import from "@/components/button-styles".
export { buttonClass };
export type { ButtonSize, ButtonVariant };

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  className = "",
  children,
  disabled,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={buttonClass(variant, size, className)}
    >
      {loading && <Spinner className={size === "sm" ? "h-3 w-3" : "h-4 w-4"} />}
      {children}
    </button>
  );
}


/* -------------------------------------------------------------------------
 * Surfaces — a hairline, never a shadow. A card sitting on a page does not
 * float; only modals, popovers and a scrolled nav do.
 * ---------------------------------------------------------------------- */
export function Panel({
  title,
  description,
  icon,
  action,
  children,
  className = "",
  tone = "default",
}: {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  tone?: "default" | "danger";
}) {
  return (
    <section
      className={`overflow-hidden rounded-xl border bg-card ${
        tone === "danger" ? "border-danger/40" : "border-border"
      } ${className}`}
    >
      <header
        className={`flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4 ${
          tone === "danger"
            ? "border-danger/25 bg-warn-bg/25"
            : "border-border bg-surface"
        }`}
      >
        <div className="min-w-0">
          <h2
            className={`flex items-center gap-2 text-sm font-semibold ${
              tone === "danger" ? "text-danger" : "text-foreground"
            }`}
          >
            {icon}
            {title}
          </h2>
          {description && (
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          )}
        </div>
        {action}
      </header>
      {children && <div className="p-5">{children}</div>}
    </section>
  );
}

/* -------------------------------------------------------------------------
 * Feedback
 * ---------------------------------------------------------------------- */

/** Inline error with a retry affordance. Used instead of silent failures. */
export function ErrorState({
  message,
  onRetry,
  className = "",
}: {
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={`flex flex-col items-center gap-3 rounded-xl border border-danger/30 bg-warn-bg/20 px-5 py-8 text-center ${className}`}
    >
      <AlertCircle className="h-5 w-5 text-danger" aria-hidden />
      <p className="text-sm text-foreground">{message}</p>
      {onRetry && (
        <button onClick={onRetry} className={buttonClass("secondary", "sm")}>
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          Try again
        </button>
      )}
    </div>
  );
}

/** Field-level error message, announced to assistive tech. */
export function FieldError({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return (
    <p role="alert" className="mt-2 flex items-start gap-1.5 text-xs text-danger">
      <AlertCircle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

/**
 * A neutral, non-alarming status message. Every message here says what to do
 * next, so it is never styled as a failure unless it is one.
 */
export function Notice({
  children,
  tone = "info",
  className = "",
}: {
  children: React.ReactNode;
  tone?: "info" | "warn";
  className?: string;
}) {
  if (!children) return null;
  return (
    <p
      role="status"
      className={`rounded-lg border px-4 py-2.5 text-sm ${
        tone === "warn"
          ? "border-warn/30 bg-warn-bg/40 text-warn-foreground"
          : "border-border bg-muted text-muted-foreground"
      } ${className}`}
    >
      {children}
    </p>
  );
}

/** Full-page spinner for the initial auth check. */
export function PageLoader({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden />
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`shimmer relative overflow-hidden rounded-lg bg-muted ${className}`}
    />
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="px-5 py-14 text-center">
      <p className="text-sm font-semibold">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">{body}</p>
      {action && <div className="mt-6 flex justify-center">{action}</div>}
    </div>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return <Loader2 className={`${className} animate-spin`} aria-hidden />;
}

/**
 * Small uppercase state label. Deliberately monochrome: colour on this
 * product means information, and "SUBMITTED" is a name, not a measurement.
 * It rides alongside the status rail so state never depends on colour alone.
 */
export function StateLabel({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: "default" | "warn" | "danger";
}) {
  const tones = {
    default: "bg-muted text-muted-foreground",
    warn: "bg-warn-bg text-warn-foreground",
    danger: "bg-warn-bg text-danger",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-xs uppercase tracking-[0.03em] ${tones[tone]}`}
    >
      {children}
    </span>
  );
}
