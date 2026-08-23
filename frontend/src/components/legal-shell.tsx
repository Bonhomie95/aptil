import Link from "next/link";
import { SiteFooter } from "@/components/site-footer";
import { Navbar } from "@/components/navbar";

export function LegalShell({
  title,
  updated,
  children,
}: {
  title: string;
  updated: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <Navbar />
      <main id="main" className="min-h-screen">
        <article className="mx-auto max-w-3xl px-4 pb-20 pt-32 lg:px-8">
          <h1 className="font-display text-[2.5rem] leading-[1.1] tracking-[-0.02em] sm:text-5xl">
            {title}
          </h1>
          <p className="mt-3 text-sm text-muted-foreground">Last updated {updated}</p>
          <div className="mt-12 space-y-8 text-sm leading-relaxed text-muted-foreground">
            {children}
          </div>
          <p className="mt-14 text-sm">
            <Link href="/" className="text-accent">
              ← Back to Aptil
            </Link>
          </p>
        </article>
      </main>
      <SiteFooter marketing />
    </>
  );
}

export function Section({
  heading,
  children,
}: {
  heading: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h2 className="text-base font-semibold text-foreground">{heading}</h2>
      <div className="mt-2 space-y-3">{children}</div>
    </section>
  );
}
