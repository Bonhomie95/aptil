"use client";

import { Reveal, RevealItem } from "@/components/reveal";

// The ATS platforms we can apply on automatically once a role is found. The
// roles themselves are discovered across the open web, not from this fixed
// list — see the heading copy below.
const sources = ["Greenhouse", "Lever", "Ashby", "Workday", "USAJOBS"];

export function Sources() {
  return (
    <section className="border-y border-border bg-surface px-4 py-10 lg:px-8">
      <Reveal className="mx-auto max-w-[1200px] text-center">
        <RevealItem>
          <p className="text-xs uppercase tracking-[0.1em] text-muted-foreground">
            We search the open web for roles that match your CV — and apply
            automatically on
          </p>
        </RevealItem>
        <RevealItem>
          <ul className="mt-6 flex flex-wrap items-center justify-center gap-x-12 gap-y-4">
            {sources.map((s) => (
              <li
                key={s}
                className="text-xl tracking-[-0.01em] text-subtle transition-colors duration-200 ease-ease hover:text-foreground sm:text-2xl"
              >
                {s}
              </li>
            ))}
          </ul>
        </RevealItem>
      </Reveal>
    </section>
  );
}
