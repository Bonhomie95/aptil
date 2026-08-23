"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { Reveal, RevealItem } from "@/components/reveal";

// Static copy, answered from what the product actually does — nothing here
// is read from the backend, so it can never drift out of sync with an API
// response, but it also can't be wrong about a real feature. Keep it that way.
const faqs = [
  {
    q: "Is this actually me applying, or does Aptil impersonate me?",
    a: "Aptil fills out and submits official ATS application forms with your information, role by role, only where you've given consent. Nothing bypasses a CAPTCHA, and nothing logs into a site as you without a credential you added yourself.",
  },
  {
    q: "Do I need a credit card to start?",
    a: "No. The free plan includes a working set of applications and mock interviews with no card required. Upgrade only when you want more volume.",
  },
  {
    q: "What happens to my résumé and account data?",
    a: "Credentials are encrypted at rest, unique per site. You can export a full copy of your data or delete your account in one click, anytime, from Settings.",
  },
  {
    q: "Which job boards and ATSes does Aptil use?",
    a: "We search the open web for roles matching your CV — wherever they are posted, not a fixed list of companies — then deduplicate so you never see the same posting twice. When a role lives on an ATS we support (Greenhouse, Lever, Ashby, Workday), we apply for you automatically; otherwise we hand you the posting ready to finish.",
  },
  {
    q: "Can I review an application before it's submitted?",
    a: "Yes. Every match carries the reasoning behind it, and anything that needs your input — a screening question, a missing field — pauses for you instead of guessing.",
  },
];

export function FAQ() {
  const [open, setOpen] = useState<number | null>(0);

  return (
    <section id="faq" className="mx-auto max-w-[760px] px-4 py-24 lg:px-8">
      <Reveal className="mb-12 text-center">
        <RevealItem>
          <p className="mb-3 text-xs uppercase tracking-[0.1em] text-muted-foreground">
            Questions
          </p>
        </RevealItem>
        <RevealItem>
          <h2 className="font-display text-3xl tracking-[-0.02em] sm:text-[2.75rem] sm:leading-[1.1]">
            Before you sign up
          </h2>
        </RevealItem>
      </Reveal>

      <Reveal
        as="section"
        className="divide-y divide-border rounded-xl border border-border bg-card shadow-card"
      >
        {faqs.map((item, i) => {
          const isOpen = open === i;
          return (
            <RevealItem key={item.q}>
              <button
                type="button"
                aria-expanded={isOpen}
                aria-controls={`faq-panel-${i}`}
                onClick={() => setOpen(isOpen ? null : i)}
                className="flex w-full items-center justify-between gap-4 px-6 py-5 text-left text-sm font-semibold transition-colors duration-200 ease-ease hover:text-accent sm:text-base"
              >
                {item.q}
                <ChevronDown
                  aria-hidden
                  className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 ease-ease ${
                    isOpen ? "rotate-180" : ""
                  }`}
                />
              </button>
              <div
                id={`faq-panel-${i}`}
                role="region"
                className={`grid transition-[grid-template-rows] duration-200 ease-ease ${
                  isOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
                }`}
              >
                <div className="overflow-hidden">
                  <p className="px-6 pb-5 text-sm leading-relaxed text-muted-foreground">
                    {item.a}
                  </p>
                </div>
              </div>
            </RevealItem>
          );
        })}
      </Reveal>
    </section>
  );
}
