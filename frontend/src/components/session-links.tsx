"use client";

import Link from "next/link";
import { useHasSession } from "@/hooks/use-has-session";
import { buttonClass } from "@/components/button-styles";

/**
 * Marketing-surface links whose destination depends on whether the visitor is
 * already signed in.
 *
 * Kept as small client components so the pages around them stay server
 * components — only these hydrate.
 *
 * Signed in, the answer is "Dashboard": offering "Log in" to someone who
 * already is reads as though the session were lost, and "Get started" invites
 * them to make a second account.
 */
export function FooterAuthLink({ className = "" }: { className?: string }) {
  const signedIn = useHasSession();
  return (
    <Link href={signedIn ? "/dashboard" : "/login"} className={className}>
      {signedIn ? "Dashboard" : "Log in"}
    </Link>
  );
}

export function NavAuthLinks() {
  const signedIn = useHasSession();

  if (signedIn) {
    return (
      <Link href="/dashboard" className={buttonClass("primary", "md")}>
        Go to dashboard
      </Link>
    );
  }
  return (
    <>
      <Link
        href="/login"
        className="hidden rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors duration-200 ease-ease hover:text-foreground sm:block"
      >
        Log in
      </Link>
      <Link href="/register" className={buttonClass("primary", "md")}>
        Get started
      </Link>
    </>
  );
}

/** The mobile drawer's auth row. Null when signed in — the bar already shows it. */
export function MobileAuthLink({ onNavigate }: { onNavigate?: () => void }) {
  const signedIn = useHasSession();
  if (signedIn) return null;
  return (
    <li className="sm:hidden">
      <Link
        href="/login"
        onClick={onNavigate}
        className="block rounded-lg px-4 py-2.5 text-sm text-muted-foreground"
      >
        Log in
      </Link>
    </li>
  );
}
