"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { MailCheck } from "lucide-react";
import { Button } from "@/components/ui";
import { api } from "@/lib/api";

/**
 * "Verify your email" panel with a resend button.
 *
 * The cooldown is authoritative on the server (30s, doubling, capped at 30
 * minutes); the server returns `next_cooldown_seconds` and we mirror it here,
 * persisting the deadline in localStorage so a refresh doesn't reset the timer.
 */
export function VerifyPending({
  email,
  justRegistered = false,
}: {
  email: string;
  justRegistered?: boolean;
}) {
  const storageKey = `aptil_resend_until_${email.toLowerCase()}`;
  const [cooldown, setCooldown] = useState(0);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const startCountdown = useCallback((seconds: number) => {
    if (timer.current) clearInterval(timer.current);
    setCooldown(seconds);
    if (seconds <= 0) return;
    timer.current = setInterval(() => {
      setCooldown((s) => {
        if (s <= 1) {
          if (timer.current) clearInterval(timer.current);
          return 0;
        }
        return s - 1;
      });
    }, 1000);
  }, []);

  useEffect(() => {
    // Registration already sent one email, so start the clock immediately
    // rather than offering a resend that the server will refuse.
    if (justRegistered && !localStorage.getItem(storageKey)) {
      localStorage.setItem(storageKey, String(Date.now() + 30_000));
    }
    const until = Number(localStorage.getItem(storageKey) || 0);
    const remaining = Math.ceil((until - Date.now()) / 1000);
    // Deferred to a task so the first state update is not synchronous inside
    // the effect body (which would cause a cascading render).
    const start = setTimeout(() => {
      if (remaining > 0) startCountdown(remaining);
    }, 0);
    return () => {
      clearTimeout(start);
      if (timer.current) clearInterval(timer.current);
    };
  }, [storageKey, startCountdown, justRegistered]);

  async function resend() {
    if (cooldown > 0 || busy) return;
    setBusy(true);
    setNote(null);
    try {
      const { sent, next_cooldown_seconds } = await api.resendVerification(email);
      localStorage.setItem(
        storageKey,
        String(Date.now() + next_cooldown_seconds * 1000),
      );
      startCountdown(next_cooldown_seconds);
      setNote(
        sent
          ? "Verification email sent — check your inbox (and spam folder)."
          : `Please wait ${next_cooldown_seconds}s before requesting another email.`,
      );
    } catch (err) {
      setNote(
        err instanceof Error
          ? err.message
          : "Couldn't send right now. Try again in a moment.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-center text-center">
      <MailCheck className="mb-4 h-8 w-8 text-subtle" aria-hidden />
      <p className="text-sm text-muted-foreground">
        We sent a verification link to{" "}
        <b className="break-anywhere font-medium text-foreground">{email}</b>. Click it
        to activate your account, then log in.
      </p>

      {note && (
        <p role="status" className="mt-4 text-sm text-muted-foreground">
          {note}
        </p>
      )}

      <Button
        onClick={resend}
        size="lg"
        loading={busy}
        disabled={cooldown > 0}
        className="mt-6 w-full"
      >
        {busy
          ? "Sending…"
          : cooldown > 0
            ? `Resend in ${cooldown}s`
            : "Resend verification email"}
      </Button>

      <Link href="/login" className="mt-4 text-sm text-accent">
        Back to login
      </Link>
    </div>
  );
}
