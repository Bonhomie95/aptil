"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Menu, X } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { MobileAuthLink, NavAuthLinks } from "@/components/session-links";

const links: [string, string][] = [
  ["Features", "/#features"],
  ["How it works", "/#how"],
  ["Pricing", "/#pricing"],
];

/**
 * Marketing header. A plain 64px bar with a hairline, not a floating pill:
 * the pill was the loudest element on a page whose whole argument is
 * restraint, and it made the anchor-offset maths guesswork.
 *
 * The hairline only appears once the page has scrolled, so the header is
 * invisible over the hero and present everywhere else.
 */
export function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className="fixed inset-x-0 top-0 z-50">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <nav
        aria-label="Main"
        className={`bg-background/90 backdrop-blur transition-colors duration-200 ease-ease ${
          scrolled || open ? "border-b border-border" : "border-b border-transparent"
        }`}
      >
        <div className="mx-auto flex h-16 max-w-[1200px] items-center gap-6 px-4 lg:px-8">
          <Link
            href="/"
            className="text-xl tracking-[-0.01em] text-accent sm:text-2xl"
          >
            Aptil
          </Link>

          <div className="hidden items-center gap-1 md:flex">
            {links.map(([label, href]) => (
              <a
                key={href}
                href={href}
                className="rounded-lg px-4 py-2 text-sm text-muted-foreground transition-colors duration-200 ease-ease hover:bg-muted hover:text-foreground"
              >
                {label}
              </a>
            ))}
          </div>

          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            <NavAuthLinks />
            <button
              aria-label={open ? "Close menu" : "Open menu"}
              aria-expanded={open}
              aria-controls="marketing-nav"
              onClick={() => setOpen((o) => !o)}
              className="grid h-9 w-9 place-items-center rounded-lg text-muted-foreground transition-colors duration-200 ease-ease hover:bg-muted hover:text-foreground md:hidden"
            >
              {open ? (
                <X className="h-5 w-5" aria-hidden />
              ) : (
                <Menu className="h-5 w-5" aria-hidden />
              )}
            </button>
          </div>
        </div>

        {open && (
          <ul
            id="marketing-nav"
            className="border-t border-border bg-background px-4 py-2 md:hidden"
          >
            {links.map(([label, href]) => (
              <li key={href}>
                <a
                  href={href}
                  onClick={() => setOpen(false)}
                  className="block rounded-lg px-4 py-2.5 text-sm text-muted-foreground"
                >
                  {label}
                </a>
              </li>
            ))}
            <MobileAuthLink onNavigate={() => setOpen(false)} />
          </ul>
        )}
      </nav>
    </header>
  );
}
