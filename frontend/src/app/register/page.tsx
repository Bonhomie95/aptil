"use client";

import Link from "next/link";
import { useState } from "react";
import {
  AuthShell,
  Field,
  GoogleButton,
  OrDivider,
  PasswordStrength,
} from "@/components/auth-shell";
import { useRedirectIfAuthenticated } from "@/hooks/use-redirect-if-authenticated";
import { VerifyPending } from "@/components/verify-pending";
import { Button, FieldError, PageLoader } from "@/components/ui";
import { api, googleLoginUrl } from "@/lib/api";

export default function RegisterPage() {
  // Already signed in? No reason to offer a second account.
  const { checking } = useRedirectIfAuthenticated();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [fullName, setFullName] = useState("");
  const [terms, setTerms] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);

  function validate(): boolean {
    const errs: Record<string, string> = {};
    if (password.length < 8) errs.password = "Use at least 8 characters.";
    if (confirm !== password) errs.confirm = "Passwords don't match.";
    if (!terms) errs.terms = "Please accept the Terms and Privacy Policy.";
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    // Catch these in the browser so the user isn't round-tripping to find out.
    if (!validate()) return;
    setLoading(true);
    try {
      await api.register({
        email,
        password,
        full_name: fullName || undefined,
        accepted_terms: terms,
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  if (checking) {
    return (
      <AuthShell title="Create your account">
        <PageLoader label="Checking your session" />
      </AuthShell>
    );
  }

  if (done) {
    return (
      <AuthShell title="Verify your email">
        <VerifyPending email={email} justRegistered />
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Create your account"
      subtitle="Free to start — no credit card needed."
    >
      <GoogleButton href={googleLoginUrl} label="Sign up with Google" />
      <OrDivider />
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <Field
          label="Full name"
          value={fullName}
          onChange={setFullName}
          autoComplete="name"
          optional
          hint="Used on your résumé and applications."
        />
        <Field
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          required
          autoComplete="email"
        />
        <div>
          <Field
            label="Password"
            type="password"
            value={password}
            onChange={(v) => {
              setPassword(v);
              setFieldErrors((f) => ({ ...f, password: "" }));
            }}
            required
            minLength={8}
            autoComplete="new-password"
            error={fieldErrors.password || null}
          />
          <PasswordStrength value={password} />
        </div>
        <Field
          label="Confirm password"
          type="password"
          value={confirm}
          onChange={(v) => {
            setConfirm(v);
            setFieldErrors((f) => ({ ...f, confirm: "" }));
          }}
          required
          autoComplete="new-password"
          error={fieldErrors.confirm || null}
        />

        <div>
          <label className="flex cursor-pointer items-start gap-2.5 text-sm">
            <input
              type="checkbox"
              checked={terms}
              onChange={(e) => {
                setTerms(e.target.checked);
                setFieldErrors((f) => ({ ...f, terms: "" }));
              }}
              aria-describedby={fieldErrors.terms ? "terms-error" : undefined}
              className="mt-0.5 h-4 w-4 shrink-0 rounded-sm border-border accent-[var(--color-accent)]"
            />
            <span className="text-muted-foreground">
              I agree to the{" "}
              <Link href="/terms" target="_blank" className="text-accent">
                Terms of Service
              </Link>{" "}
              and{" "}
              <Link href="/privacy" target="_blank" className="text-accent">
                Privacy Policy
              </Link>
              .
            </span>
          </label>
          {fieldErrors.terms && (
            <p id="terms-error" role="alert" className="mt-1.5 text-xs text-danger">
              {fieldErrors.terms}
            </p>
          )}
        </div>

        <FieldError>{error}</FieldError>
        <Button type="submit" size="lg" loading={loading} className="w-full">
          {loading ? "Creating…" : "Create account"}
        </Button>
      </form>
      <div className="mt-6 border-t border-border pt-6 text-center text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link href="/login" className="text-accent">
          Log in
        </Link>
      </div>
    </AuthShell>
  );
}
