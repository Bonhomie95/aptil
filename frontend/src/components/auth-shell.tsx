"use client";

import Link from "next/link";
import { useId } from "react";
import { AlertCircle } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";

/**
 * Auth is seen at 3am on a phone, usually after something went wrong. So the
 * shell is deliberately plain — one card, no marketing chrome, nothing to
 * read — and all the design effort goes into the error states inside it.
 */
export function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <main
      id="main"
      className="flex min-h-screen flex-col items-center justify-center px-4 py-10"
    >
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-md rounded-xl border border-border bg-surface p-6 shadow-raised sm:p-8">
        <div className="text-center">
          <Link href="/" className="text-sm text-accent">
            Aptil
          </Link>
          <h1 className="mt-3 text-2xl tracking-[-0.02em] sm:text-[2rem] sm:leading-10">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-1 text-sm text-muted-foreground sm:text-base">
              {subtitle}
            </p>
          )}
        </div>
        <div className="mt-6">{children}</div>
      </div>
    </main>
  );
}

export function Field({
  label,
  value,
  onChange,
  type = "text",
  required,
  autoComplete,
  hint,
  error,
  minLength,
  id,
  autoFocus,
  optional,
  labelAction,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  required?: boolean;
  autoComplete?: string;
  hint?: string;
  error?: string | null;
  minLength?: number;
  id?: string;
  autoFocus?: boolean;
  /** Marks the field as optional. Most fields are required, so calling out the
   *  exceptions is quieter than starring nearly every label. */
  optional?: boolean;
  /** Rendered beside the label — kept outside <label> so it never becomes
   *  part of the field's accessible name. */
  labelAction?: React.ReactNode;
  placeholder?: string;
}) {
  // useId, not a module counter: the counter produced a different id on every
  // render (so the DOM attribute churned on each keystroke and password
  // managers lost the field), and a different one on the server than on the
  // client, which is a hydration mismatch waiting to happen.
  const generated = useId();
  const fieldId = id ?? generated;
  const hintId = hint ? `${fieldId}-hint` : undefined;
  const errorId = error ? `${fieldId}-error` : undefined;

  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <label htmlFor={fieldId} className="block text-xs font-medium">
          {label}
          {optional && (
            <span className="ml-1.5 font-normal text-muted-foreground">(optional)</span>
          )}
        </label>
        {labelAction}
      </div>
      <div className="relative">
        <input
          id={fieldId}
          type={type}
          value={value}
          required={required}
          minLength={minLength}
          autoComplete={autoComplete}
          autoFocus={autoFocus}
          placeholder={placeholder}
          aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined}
          aria-invalid={error ? true : undefined}
          onChange={(e) => onChange(e.target.value)}
          className={`h-12 w-full rounded-lg border bg-card px-4 outline-none transition-colors duration-200 ease-ease placeholder:text-subtle ${
            error ? "border-danger pr-11" : "border-border focus:border-accent"
          }`}
        />
        {error && (
          <AlertCircle
            aria-hidden
            className="pointer-events-none absolute right-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-danger"
          />
        )}
      </div>
      {hint && !error && (
        <p id={hintId} className="mt-1.5 text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} role="alert" className="mt-1.5 text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export function GoogleButton({
  href,
  label = "Continue with Google",
}: {
  href: string;
  label?: string;
}) {
  return (
    <a
      href={href}
      className="flex h-12 w-full items-center justify-center gap-2 rounded-lg border border-border bg-card text-sm font-medium transition-colors duration-200 ease-ease hover:border-foreground/40 hover:bg-muted"
    >
      <svg className="h-4 w-4" viewBox="0 0 24 24" aria-hidden>
        <path
          fill="#4285F4"
          d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
        />
        <path
          fill="#34A853"
          d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z"
        />
        <path
          fill="#FBBC05"
          d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84z"
        />
        <path
          fill="#EA4335"
          d="M12 4.75c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 1.46 14.97.5 12 .5A11 11 0 0 0 2.18 7.06l3.66 2.84C6.71 6.68 9.14 4.75 12 4.75z"
        />
      </svg>
      {label}
    </a>
  );
}

/** Live strength meter so users learn the rule before the server rejects them. */
export function PasswordStrength({ value }: { value: string }) {
  if (!value) return null;
  const checks = [
    value.length >= 8,
    value.length >= 12,
    /[A-Z]/.test(value) && /[a-z]/.test(value),
    /\d/.test(value) || /[^A-Za-z0-9]/.test(value),
  ];
  const score = checks.filter(Boolean).length;
  const labels = ["Too short", "Weak", "Fair", "Good", "Strong"];
  // Colour is a second signal here, never the only one — the word beneath
  // says the same thing.
  const colors = ["bg-danger", "bg-danger", "bg-warn", "bg-positive", "bg-positive"];
  return (
    <div className="mt-2">
      <div className="flex gap-1" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className={`h-1 flex-1 rounded-sm ${i < score ? colors[score] : "bg-border"}`}
          />
        ))}
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground" aria-live="polite">
        Password strength: {labels[score]}
        {value.length < 8 && " — at least 8 characters"}
      </p>
    </div>
  );
}

/** "or" rule between the social button and the form. */
export function OrDivider() {
  return (
    <div className="my-5 flex items-center gap-3 text-xs text-subtle">
      <span className="h-px flex-1 bg-border" />
      or
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}
