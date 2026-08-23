"use client";

import { useSyncExternalStore } from "react";
import { tokenStore } from "@/lib/api";

// Nothing to subscribe to: a token appearing mid-render would mean the user
// signed in in another tab, and the next navigation picks that up anyway.
const subscribeNever = () => () => {};

/**
 * Whether this browser holds a session, read from localStorage rather than
 * React state.
 *
 * The server snapshot is `false` because there is no localStorage during SSR,
 * so the server HTML and the first client render agree and React re-renders
 * with the real value straight after hydration. Reading it with useState
 * instead would render "signed out" on the server and "signed in" on the
 * client — a hydration mismatch.
 *
 * This says a token EXISTS, not that it is still valid. Good enough for
 * deciding which link to show; anything that acts on the session must ask the
 * API (see useSession / useRedirectIfAuthenticated).
 */
export function useHasSession(): boolean {
  return useSyncExternalStore(
    subscribeNever,
    () => Boolean(tokenStore.access()),
    () => false,
  );
}
