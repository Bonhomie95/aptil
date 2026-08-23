"use client";

import Link from "next/link";
import { useState } from "react";
import { MailCheck } from "lucide-react";
import { AuthShell, Field } from "@/components/auth-shell";
import { Button, FieldError, buttonClass } from "@/components/ui";
import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.forgotPassword(email);
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't send the reset link.");
    } finally {
      setLoading(false);
    }
  }

  if (sent) {
    return (
      <AuthShell title="Check your inbox">
        <div className="flex flex-col items-center text-center">
          <MailCheck className="mb-4 h-8 w-8 text-subtle" aria-hidden />
          {/* Deliberately identical whether or not the account exists — the
              response must not reveal which addresses are registered. */}
          <p className="text-sm text-muted-foreground">
            If an account exists for{" "}
            <b className="break-anywhere font-medium text-foreground">{email}</b>,
            we&apos;ve sent a password reset link. It expires in 60 minutes.
          </p>
          <Link
            href="/login"
            className={buttonClass("primary", "lg", "mt-6 w-full")}
          >
            Back to login
          </Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Reset your password"
      subtitle="We'll email you a link to set a new one."
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <Field
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          required
          autoComplete="email"
          autoFocus
        />
        <FieldError>{error}</FieldError>
        <Button type="submit" size="lg" loading={loading} className="w-full">
          {loading ? "Sending…" : "Send reset link"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        Remembered it?{" "}
        <Link href="/login" className="text-accent">
          Back to login
        </Link>
      </p>
    </AuthShell>
  );
}
