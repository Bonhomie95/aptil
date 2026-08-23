"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import {
  Briefcase,
  CreditCard,
  HelpCircle,
  LayoutGrid,
  LogOut,
  Menu,
  Mic,
  Settings,
  X,
} from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { WorkingLine } from "@/components/signals";
import { SiteFooter } from "@/components/site-footer";
import { api } from "@/lib/api";

type Item = { href: string; label: string; icon: typeof LayoutGrid };

const NAV: Item[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutGrid },
  { href: "/jobs", label: "Jobs", icon: Briefcase },
  { href: "/interview", label: "Interview", icon: Mic },
  { href: "/plans", label: "Plans", icon: CreditCard },
  { href: "/settings", label: "Settings", icon: Settings },
];

function Brand() {
  return (
    <Link href="/dashboard" className="flex items-center gap-2 px-2">
      <span
        aria-hidden
        className="grid h-8 w-8 shrink-0 place-items-center rounded-sm bg-accent text-base text-accent-foreground"
      >
        A
      </span>
      <span className="min-w-0">
        <span className="block text-xl leading-6 tracking-[-0.01em] text-accent">
          Aptil
        </span>
        <span className="block text-xs text-muted-foreground">Career Suite</span>
      </span>
    </Link>
  );
}

function NavLinks({
  pathname,
  onNavigate,
}: {
  pathname: string;
  onNavigate?: () => void;
}) {
  return (
    <>
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={`flex items-center gap-4 rounded-lg px-4 py-2 text-sm transition-colors duration-200 ease-ease ${
              active
                ? "bg-accent-soft font-medium text-accent"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden />
            {label}
          </Link>
        );
      })}
    </>
  );
}

/**
 * The signed-in chrome: a 256px rail on desktop, a drawer on small screens.
 *
 * A rail rather than a top bar because this product is a workspace someone
 * leaves open — the current section should stay visible without a hover, and
 * the pipeline needs the full page width beside it.
 */
export function AppShell({
  email,
  children,
  toolbar,
  working = false,
  workingLabel,
}: {
  email?: string;
  children: React.ReactNode;
  /** Page-specific controls for the top bar (search, filters). */
  toolbar?: React.ReactNode;
  /** Drives the working line — background work, not a click the user is
   *  waiting on. */
  working?: boolean;
  workingLabel?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  // Remember which route the drawer was opened on. Deriving `open` from that
  // closes it on navigation without an effect that sets state.
  const [openedOn, setOpenedOn] = useState<string | null>(null);
  const open = openedOn === pathname;

  async function logout() {
    await api.logout();
    router.push("/login");
  }

  return (
    <div className="min-h-screen lg:flex">
      <WorkingLine active={working} label={workingLabel ?? "Working"} />
      <a href="#main" className="skip-link">
        Skip to content
      </a>

      {/* Desktop rail */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col gap-4 border-r border-border bg-card p-4 lg:flex">
        <div className="pb-4">
          <Brand />
        </div>
        <nav aria-label="Main" className="flex flex-1 flex-col gap-1">
          <NavLinks pathname={pathname} />
        </nav>
        <div className="flex flex-col gap-1 border-t border-border pt-4">
          <Link
            href="/#how"
            className="flex items-center gap-4 rounded-lg px-4 py-2 text-sm text-muted-foreground transition-colors duration-200 ease-ease hover:bg-muted hover:text-foreground"
          >
            <HelpCircle className="h-5 w-5" aria-hidden />
            Help
          </Link>
          <button
            onClick={logout}
            className="flex items-center gap-4 rounded-lg px-4 py-2 text-left text-sm text-muted-foreground transition-colors duration-200 ease-ease hover:bg-muted hover:text-foreground"
          >
            <LogOut className="h-[18px] w-[18px]" aria-hidden />
            Log out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar */}
        <header className="sticky top-0 z-30 border-b border-border bg-card/95 backdrop-blur">
          <div className="flex items-center gap-3 px-4 py-3 lg:px-8">
            <button
              aria-label={open ? "Close menu" : "Open menu"}
              aria-expanded={open}
              aria-controls="app-drawer"
              onClick={() => setOpenedOn(open ? null : pathname)}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors duration-200 ease-ease hover:bg-muted hover:text-foreground lg:hidden"
            >
              {open ? (
                <X className="h-5 w-5" aria-hidden />
              ) : (
                <Menu className="h-5 w-5" aria-hidden />
              )}
            </button>
            <div className="lg:hidden">
              <Brand />
            </div>
            <div className="ml-auto flex min-w-0 items-center gap-3">
              {toolbar}
              <ThemeToggle />
              {email && (
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    className="hidden max-w-[16rem] truncate text-sm text-muted-foreground lg:inline"
                    title={email}
                  >
                    {email}
                  </span>
                  <span
                    aria-hidden
                    className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-border bg-tile text-sm text-muted-foreground"
                  >
                    {email.trim().charAt(0).toUpperCase()}
                  </span>
                </span>
              )}
            </div>
          </div>

          {open && (
            <nav
              id="app-drawer"
              aria-label="Sections"
              className="flex flex-col gap-1 border-t border-border px-4 py-3 lg:hidden"
            >
              <NavLinks
                pathname={pathname}
                onNavigate={() => setOpenedOn(null)}
              />
              <button
                onClick={logout}
                className="flex items-center gap-4 rounded-lg px-4 py-2 text-left text-sm text-muted-foreground"
              >
                <LogOut className="h-[18px] w-[18px]" aria-hidden />
                Log out
              </button>
            </nav>
          )}
        </header>

        <main id="main" className="flex-1 px-4 py-8 lg:px-8">
          <div className="mx-auto w-full max-w-[1200px]">{children}</div>
        </main>

        <SiteFooter />
      </div>
    </div>
  );
}

/**
 * Page title block. Kept here so every in-app screen shares the same rhythm:
 * 32px title, one muted sentence, actions right-aligned on the baseline.
 */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl tracking-[-0.02em] sm:text-[32px] sm:leading-10">
          {title}
        </h1>
        {description && (
          <p className="mt-1 text-sm text-muted-foreground sm:text-base">
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
