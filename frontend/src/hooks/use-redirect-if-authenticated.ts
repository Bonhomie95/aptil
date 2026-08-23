"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useHasSession } from "@/hooks/use-has-session";
import { ApiError, api, tokenStore } from "@/lib/api";

/**
 * Guard for the login and register pages: an already-signed-in visitor is sent
 * into the app instead of being shown a form they don't need.
 *
 * Returns `checking` — render a placeholder while it is true, so the form never
 * flashes in front of someone about to be redirected.
 *
 * Three cases the naive version gets wrong:
 *
 *  - **No token.** Resolves without a network call, so the common case (a
 *    logged-out visitor) has zero added latency and no loading state at all.
 *  - **Stale token.** A token that no longer validates must leave the visitor on
 *    the form, not strand them on a spinner. We clear it and let them log in.
 *  - **Unverified email.** Sending everyone to `/dashboard` would bounce an
 *    unverified user straight back here — that page signs them out and returns
 *    to `/login?reason=verify` — a visible round trip. So the destination is
 *    resolved here instead: unverified stays on the form, and an unonboarded
 *    user goes to `/onboarding` directly rather than via a redirecting
 *    `/dashboard`.
 */
export function useRedirectIfAuthenticated() {
  const router = useRouter();
  const hasToken = useHasSession();
  const [resolved, setResolved] = useState(false);

  useEffect(() => {
    // No token: nothing to check, and no state to set.
    if (!hasToken) return;

    let cancelled = false;
    (async () => {
      try {
        const me = await api.me();
        if (cancelled) return;

        if (!me.is_email_verified) {
          // Don't hand them to a page that will only send them back.
          tokenStore.clear();
          setResolved(true);
          return;
        }
        router.replace(me.onboarding_completed ? "/dashboard" : "/onboarding");
      } catch (err) {
        if (cancelled) return;
        // 401/403 means the stored token is no longer good. Anything else
        // (network, server error) shouldn't trap them either — show the form.
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          tokenStore.clear();
        }
        setResolved(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [hasToken, router]);

  return { checking: hasToken && !resolved };
}
