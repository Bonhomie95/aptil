"use client";

import Link from "next/link";
import { Reveal, RevealItem } from "@/components/reveal";
import { buttonClass } from "@/components/ui";

export function CTA() {
  return (
    <section className="mx-auto max-w-[1200px] px-4 pb-24 lg:px-8">
      <Reveal>
        <RevealItem>
          <div className="rounded-xl border border-border bg-card px-6 py-16 text-center shadow-card transition-shadow duration-200 ease-ease hover:shadow-float sm:px-12">
            <h2 className="font-display text-3xl tracking-[-0.02em] sm:text-[2.5rem] sm:leading-[1.1]">
              Your next role is out there. Let&apos;s go get it.
            </h2>
            <p className="mx-auto mt-4 max-w-md text-muted-foreground">
              Set up your profile once. Aptil handles the search, the applications, and
              your interview prep. Free to start, no card required.
            </p>
            <Link
              href="/register"
              className={buttonClass("primary", "lg", "mt-8")}
            >
              Create your free account
            </Link>
          </div>
        </RevealItem>
      </Reveal>
    </section>
  );
}
