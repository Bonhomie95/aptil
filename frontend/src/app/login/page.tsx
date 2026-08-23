"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AuthShell, Field, GoogleButton, OrDivider } from "@/components/auth-shell";
import { useRedirectIfAuthenticated } from "@/hooks/use-redirect-if-authenticated";
import { VerifyPending } from "@/components/verify-pending";
import { Button, FieldError, Notice, PageLoader } from "@/components/ui";
import { ApiError, api, googleLoginUrl } from "@/lib/api";

const REASONS: Record<string, string> = {
  expired: "Your session expired. Please log in again.",
  verify: "Please verify your email address before continuing.",
  google_denied: "Google sign-in was cancelled.",
  google_failed: "Google sign-in didn't complete. Try again or use your password.",
  google_no_code: "Google sign-in didn't complete. Please try again.",
  google_not_configured: "Google sign-in isn't available on this server yet.",
  reset: "Your password has been changed. Please log in.",
};

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  // Already signed in? Go to the app rather than showing a form.
  const { checking } = useRedirectIfAuthenticated();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [unverified, setUnverified] = useState(false);
  const [noticeDismissed, setNoticeDismissed] = useState(false);

  // Derived from the URL rather than copied into state by an effect.
  const reason = params.get("reason") ?? params.get("error");
  const notice = noticeDismissed
    ? null
    : reason
      ? (REASONS[reason] ?? params.get("message") ?? null)
      : null;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNoticeDismissed(true);
    setLoading(true);
    try {
      await api.login({ email, password });
      router.push("/dashboard");
    } catch (err) {
      // The backend uses this exact code so we can show the verify screen
      // instead of a dead-end error.
      if (err instanceof ApiError && err.code === "email_not_verified") {
        setUnverified(true);
      } else {
        setError(err instanceof Error ? err.message : "Login failed");
      }
    } finally {
      setLoading(false);
    }
  }

  // Hold the form back until the session check resolves, so it never flashes
  // in front of someone who is about to be redirected.
  if (checking) {
    return (
      <AuthShell title="Welcome back">
        <PageLoader label="Checking your session" />
      </AuthShell>
    );
  }

  if (unverified) {
    return (
      <AuthShell title="Verify your email">
        <VerifyPending email={email} />
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Welcome back" subtitle="Sign in to your Career Suite.">
      {notice && <Notice className="mb-4">{notice}</Notice>}
      <GoogleButton href={googleLoginUrl} />
      <OrDivider />
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <Field
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          required
          autoComplete="email"
        />
        <Field
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          required
          autoComplete="current-password"
          labelAction={
            <Link href="/forgot-password" className="text-xs text-accent">
              Forgot password?
            </Link>
          }
        />
        <FieldError>{error}</FieldError>
        <Button type="submit" size="lg" loading={loading} className="w-full">
          {loading ? "Signing in…" : "Log in"}
        </Button>
      </form>
      <div className="mt-6 border-t border-border pt-6 text-center text-sm text-muted-foreground">
        Don&apos;t have an account?{" "}
        <Link href="/register" className="text-accent">
          Sign up
        </Link>
      </div>
    </AuthShell>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<AuthShell title="Welcome back">{null}</AuthShell>}>
      <LoginInner />
    </Suspense>
  );
}
