import Link from "next/link";
import { FooterAuthLink } from "@/components/session-links";

/**
 * One footer for both surfaces. Brand, an honest copyright, and the legal
 * links compliance requires to be reachable from every page.
 *
 * `marketing` is not just about the Features/Pricing anchors: in the app the
 * visitor is signed in by definition, so an auth link there is at best noise
 * and at worst alarming — "Log in" under the dashboard reads as though the
 * session had dropped.
 */
export function SiteFooter({ marketing = false }: { marketing?: boolean }) {
  // Computed at render. The server renders the build-time year and the browser
  // re-renders the real one; suppressHydrationWarning covers the New Year's Eve
  // mismatch. An effect + setState here would cost a render for one number.
  const year = new Date().getFullYear();

  return (
    <footer className="border-t border-border bg-surface px-4 py-8 lg:px-8">
      <div className="mx-auto flex w-full max-w-[1200px] flex-col items-center gap-4 text-center sm:flex-row sm:justify-between sm:text-left">
        <Link href="/" className="text-sm font-medium">
          Aptil
        </Link>
        <p className="text-xs text-subtle" suppressHydrationWarning>
          © {year} Aptil. Land the job, ace the interview.
        </p>
        <nav
          aria-label="Footer"
          className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-xs text-muted-foreground"
        >
          {marketing && (
            <>
              <a
                href="/#features"
                className="transition-colors duration-200 ease-ease hover:text-foreground"
              >
                Features
              </a>
              <a
                href="/#pricing"
                className="transition-colors duration-200 ease-ease hover:text-foreground"
              >
                Pricing
              </a>
            </>
          )}
          <Link
            href="/privacy"
            className="transition-colors duration-200 ease-ease hover:text-foreground"
          >
            Privacy Policy
          </Link>
          <Link
            href="/terms"
            className="transition-colors duration-200 ease-ease hover:text-foreground"
          >
            Terms of Service
          </Link>
          {marketing && (
            <FooterAuthLink className="transition-colors duration-200 ease-ease hover:text-foreground" />
          )}
        </nav>
      </div>
    </footer>
  );
}
