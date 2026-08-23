"use client";

import { Radar, Rocket, UploadCloud } from "lucide-react";
import { Reveal, RevealItem } from "@/components/reveal";
import { TiltCard } from "@/components/tilt-card";

const steps = [
  {
    icon: UploadCloud,
    step: "01",
    title: "Upload your CV once",
    body: "We parse it into a structured profile and prefill every field. Edit anything that's off — nothing is set in stone.",
  },
  {
    icon: Radar,
    step: "02",
    title: "We find & apply",
    body: "Aptil ranks real openings against your profile and applies through official ATS forms — two at a time, with your tailored résumé, and only where you've given consent.",
  },
  {
    icon: Rocket,
    step: "03",
    title: "You practice & win",
    body: "Run mock interviews built from your CV and the exact role, get scored feedback, and walk in ready.",
  },
];

export function HowItWorks() {
  return (
    <section
      id="how"
      className="border-y border-border bg-surface px-4 py-24 lg:px-8"
    >
      <div className="mx-auto max-w-[1200px]">
        <Reveal className="mx-auto mb-12 max-w-2xl text-center">
          <RevealItem>
            <p className="mb-3 text-xs uppercase tracking-[0.1em] text-muted-foreground">
              How it works
            </p>
          </RevealItem>
          <RevealItem>
            <h2 className="font-display text-3xl tracking-[-0.02em] sm:text-[2.75rem] sm:leading-[1.1]">
              Three steps to your next offer
            </h2>
          </RevealItem>
        </Reveal>

        <Reveal className="grid gap-4 md:grid-cols-3">
          {steps.map((s) => (
            <RevealItem key={s.step}>
              <TiltCard className="h-full rounded-xl border border-border/40 bg-card p-7">
                <div className="mb-5 flex items-center justify-between">
                  <span
                    aria-hidden
                    className="grid h-10 w-10 place-items-center rounded-lg border border-border bg-tile text-muted-foreground"
                  >
                    <s.icon className="h-[18px] w-[18px]" />
                  </span>
                  <span
                    aria-hidden
                    className="text-2xl tabular-nums text-border"
                  >
                    {s.step}
                  </span>
                </div>
                <h3 className="text-base font-semibold">{s.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {s.body}
                </p>
              </TiltCard>
            </RevealItem>
          ))}
        </Reveal>
      </div>
    </section>
  );
}
