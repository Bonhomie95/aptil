"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AuthShell } from "@/components/auth-shell";
import { PageLoader } from "@/components/ui";
import { tokenStore } from "@/lib/api";

/**
 * Landing page for the Google OAuth redirect.
 *
 * The backend used to return raw JSON here, which the browser simply displayed
 * — the flow could never complete. It now redirects to this page with the
 * tokens in the URL *fragment* (never sent to a server, absent from logs); we
 * read them, store them, and immediately scrub the URL.
 */
export default function OAuthCallbackPage() {
  const router = useRouter();
  const handled = useRef(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;

    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const access_token = fragment.get("access_token");
    const refresh_token = fragment.get("refresh_token");

    if (!access_token || !refresh_token) {
      // Deferred so the state change is not synchronous within the effect.
      const id = setTimeout(() => {
        setFailed(true);
        router.replace("/login?reason=google_failed");
      }, 0);
      return () => clearTimeout(id);
    }

    tokenStore.set({ access_token, refresh_token });
    // Remove the tokens from the address bar / history entry.
    window.history.replaceState(null, "", window.location.pathname);
    router.replace("/dashboard");
  }, [router]);

  if (failed) {
    return (
      <AuthShell title="Sign-in failed">
        <p role="alert" className="text-sm text-danger">
          Sign-in didn&apos;t complete. Redirecting you back to log in…
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Signing you in…">
      <PageLoader label="Completing Google sign-in" />
    </AuthShell>
  );
}
