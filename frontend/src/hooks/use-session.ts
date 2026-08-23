"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api, setSessionExpiredHandler, tokenStore, type Me } from "@/lib/api";

type SessionState = {
  user: Me | null;
  loading: boolean;
  error: string | null;
};

/**
 * Resolve the signed-in user for a protected page.
 *
 * Distinguishes the three cases the old code collapsed into "push to /login":
 *  - no/expired credentials  -> redirect to /login
 *  - unverified email        -> redirect to /login (with a reason)
 *  - transient network error -> show a retry, keep the user where they are
 *
 * Pass `requireOnboarded` to bounce users who haven't finished the wizard.
 */
export function useSession(options: { requireOnboarded?: boolean } = {}) {
  const { requireOnboarded = false } = options;
  const router = useRouter();
  const [state, setState] = useState<SessionState>({
    user: null,
    loading: true,
    error: null,
  });
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    // A failed refresh anywhere in the app lands the user back on /login.
    setSessionExpiredHandler(() => router.replace("/login?reason=expired"));
    return () => setSessionExpiredHandler(null);
  }, [router]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      if (!tokenStore.access()) {
        router.replace("/login");
        return;
      }
      try {
        const me = await api.me();
        if (cancelled) return;

        if (!me.is_email_verified) {
          await api.logout();
          router.replace("/login?reason=verify");
          return;
        }
        if (requireOnboarded && !me.onboarding_completed) {
          router.replace("/onboarding");
          return;
        }
        setState({ user: me, loading: false, error: null });
      } catch (err) {
        if (cancelled) return;
        const status = err instanceof ApiError ? err.status : 0;
        if (status === 401 || status === 403) {
          router.replace("/login");
          return;
        }
        // Network blip or server error: don't destroy the session over it.
        setState({
          user: null,
          loading: false,
          error:
            err instanceof Error
              ? err.message
              : "Couldn't load your account. Please try again.",
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [router, requireOnboarded, reloadKey]);

  return { ...state, retry: () => setReloadKey((k) => k + 1) };
}
