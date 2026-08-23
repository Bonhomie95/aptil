"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { AuthShell } from "@/components/auth-shell";
import { buttonClass } from "@/components/ui";
import { api } from "@/lib/api";

type State = "verifying" | "success" | "error";

function VerifyEmailInner() {
  const params = useSearchParams();
  const token = params.get("token");
  // A missing token is knowable at render time — no effect or state needed.
  const [state, setState] = useState<State>(token ? "verifying" : "error");
  const [message, setMessage] = useState(
    token ? "" : "This link is missing its verification token.",
  );
  const ran = useRef(false);

  useEffect(() => {
    if (!token || ran.current) return; // guard against double-invoke in strict mode
    ran.current = true;
    let cancelled = false;
    api
      .verifyEmail(token)
      .then(() => {
        if (!cancelled) setState("success");
      })
      .catch((err) => {
        if (cancelled) return;
        setState("error");
        setMessage((err as Error).message || "This link is invalid or has expired.");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <AuthShell title="Email verification">
      <div className="flex flex-col items-center text-center">
        {state === "verifying" && (
          <>
            <Loader2 className="mb-4 h-8 w-8 animate-spin text-subtle" aria-hidden />
            <p className="text-sm text-muted-foreground">Verifying your email…</p>
          </>
        )}
        {state === "success" && (
          <>
            <CheckCircle2 className="mb-4 h-8 w-8 text-positive" aria-hidden />
            <p className="text-sm text-muted-foreground">
              Your email is verified. You can log in now.
            </p>
            <Link
              href="/login"
              className={buttonClass("primary", "lg", "mt-6 w-full")}
            >
              Continue to login
            </Link>
          </>
        )}
        {state === "error" && (
          <>
            <XCircle className="mb-4 h-8 w-8 text-danger" aria-hidden />
            <p className="text-sm text-muted-foreground">{message}</p>
            <Link href="/login" className="mt-6 text-sm text-accent">
              Back to login — you can resend the link there
            </Link>
          </>
        )}
      </div>
    </AuthShell>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={null}>
      <VerifyEmailInner />
    </Suspense>
  );
}
