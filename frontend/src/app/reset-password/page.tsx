"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { XCircle } from "lucide-react";
import { AuthShell, Field, PasswordStrength } from "@/components/auth-shell";
import { Button, FieldError, buttonClass } from "@/components/ui";
import { api } from "@/lib/api";

function ResetInner() {
  const router = useRouter();
  const token = useSearchParams().get("token");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const errs: Record<string, string> = {};
    if (password.length < 8) errs.password = "Use at least 8 characters.";
    if (confirm !== password) errs.confirm = "Passwords don't match.";
    setFieldErrors(errs);
    if (Object.keys(errs).length) return;

    setLoading(true);
    try {
      await api.resetPassword(token!, password);
      // The reset already signed us in; go straight to the app.
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't reset your password.");
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <AuthShell title="Invalid reset link">
        <div className="flex flex-col items-center text-center">
          <XCircle className="mb-4 h-8 w-8 text-danger" aria-hidden />
          <p className="text-sm text-muted-foreground">
            This link is missing its token. Request a new one.
          </p>
          <Link
            href="/forgot-password"
            className={buttonClass("primary", "lg", "mt-6 w-full")}
          >
            Request a new link
          </Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Set a new password"
      subtitle="Choose something you haven't used before."
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <div>
          <Field
            label="New password"
            type="password"
            value={password}
            onChange={(v) => {
              setPassword(v);
              setFieldErrors((f) => ({ ...f, password: "" }));
            }}
            required
            minLength={8}
            autoComplete="new-password"
            autoFocus
            error={fieldErrors.password || null}
          />
          <PasswordStrength value={password} />
        </div>
        <Field
          label="Confirm new password"
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
        <FieldError>{error}</FieldError>
        <Button type="submit" size="lg" loading={loading} className="w-full">
          {loading ? "Saving…" : "Set new password"}
        </Button>
      </form>
      <p className="mt-5 text-center text-xs text-muted-foreground">
        Resetting your password signs you out of all other devices.
      </p>
    </AuthShell>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<AuthShell title="Set a new password">{null}</AuthShell>}>
      <ResetInner />
    </Suspense>
  );
}
