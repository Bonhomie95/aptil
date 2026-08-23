"use client";

import {
  FileSearch,
  Gauge,
  MessageSquareText,
  SendHorizonal,
  ShieldCheck,
  Wand2,
} from "lucide-react";
import { Reveal, RevealItem } from "@/components/reveal";
import { TiltCard } from "@/components/tilt-card";

const features = [
  {
    icon: FileSearch,
    title: "Smart discovery",
    body: "We pull roles from legitimate job APIs and company ATS boards, then dedupe the same job across sites so you never apply twice.",
    span: "md:col-span-2",
  },
  {
    icon: Wand2,
    title: "Résumé tailoring",
    body: "Every application can carry a résumé rewritten for that exact role — grounded in your real experience, never fabricated.",
  },
  {
    icon: SendHorizonal,
    title: "Consent-based apply",
    body: "Applications go through official ATS channels with your permission. No shady logins, no impersonation, and we never bypass a CAPTCHA.",
  },
  {
    icon: MessageSquareText,
    title: "Mock interviews",
    body: "Practice questions generated from your CV and the target job, with instant, specific feedback and a score.",
    span: "md:col-span-2",
  },
  {
    icon: ShieldCheck,
    title: "Private by design",
    body: "Credentials are encrypted at rest, unique per site. Export everything or delete your account in one click.",
  },
  {
    icon: Gauge,
    title: "Pipeline dashboard",
    body: "Track every application as it moves: matched, applied, interviewing, offer — with the reasoning behind each match.",
  },
];

export function Features() {
  return (
    <section id="features" className="mx-auto max-w-[1200px] px-4 py-24 lg:px-8">
      <Reveal className="mx-auto mb-12 max-w-2xl text-center">
        <RevealItem>
          <p className="mb-3 text-xs uppercase tracking-[0.1em] text-muted-foreground">
            Everything in one place
          </p>
        </RevealItem>
        <RevealItem>
          <h2 className="font-display text-3xl tracking-[-0.02em] sm:text-[2.75rem] sm:leading-[1.1]">
            One platform, from search to signed offer
          </h2>
        </RevealItem>
      </Reveal>

      <Reveal className="grid gap-4 md:grid-cols-3">
        {features.map((f) => (
          <RevealItem key={f.title} className={f.span ?? ""}>
            <TiltCard className="h-full rounded-xl border border-border/40 bg-card p-6">
              <span
                aria-hidden
                className="mb-5 inline-grid h-10 w-10 place-items-center rounded-lg border border-border bg-tile text-muted-foreground"
              >
                <f.icon className="h-[18px] w-[18px]" />
              </span>
              <h3 className="text-base font-semibold">{f.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {f.body}
              </p>
            </TiltCard>
          </RevealItem>
        ))}
      </Reveal>
    </section>
  );
}
