"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { Reveal, RevealItem } from "@/components/reveal";
import { Skeleton, buttonClass } from "@/components/ui";
import { TiltCard } from "@/components/tilt-card";
import { formatPrice, plural } from "@/lib/format";
import { api, type Plan } from "@/lib/api";

/**
 * Pricing is read from the same `/plans` endpoint the in-app picker uses, so
 * the marketing page and the product can never drift apart (they were two
 * hardcoded lists before).
 */
export function Pricing() {
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api
      .plans()
      .then(setPlans)
      .catch(() => setFailed(true));
  }, []);

  return (
    <section id="pricing" className="mx-auto max-w-[1200px] px-4 py-24 lg:px-8">
      <Reveal className="mx-auto mb-12 max-w-2xl text-center">
        <RevealItem>
          <p className="mb-3 text-xs uppercase tracking-[0.1em] text-muted-foreground">
            Pricing
          </p>
        </RevealItem>
        <RevealItem>
          <h2 className="font-display text-3xl tracking-[-0.02em] sm:text-[2.75rem] sm:leading-[1.1]">
            Priced by how hard we work for you
          </h2>
        </RevealItem>
        <RevealItem>
          <p className="mt-3 text-muted-foreground">
            Start on the free plan — no credit card. Upgrade when you want more volume.
          </p>
        </RevealItem>
      </Reveal>

      {failed ? (
        <p className="text-center text-sm text-muted-foreground">
          Plan details are loading slowly.{" "}
          <Link href="/plans" className="text-accent underline underline-offset-2">
            View plans
          </Link>
        </p>
      ) : plans === null ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-80" />
          ))}
        </div>
      ) : (
        <Reveal
          className={`grid items-stretch gap-4 sm:grid-cols-2 ${
            plans.length >= 4 ? "lg:grid-cols-4" : "lg:grid-cols-3"
          }`}
        >
          {plans.map((t) => (
            <RevealItem key={t.id} className="h-full">
              <TiltCard
                className={`flex h-full flex-col rounded-xl border bg-card p-6 ${
                  t.is_featured ? "border-foreground" : "border-border/40"
                }`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <h3 className="text-base font-semibold">{t.name}</h3>
                  {t.is_featured && (
                    <span className="rounded-sm bg-tile px-2 py-0.5 text-xs uppercase tracking-[0.03em] text-muted-foreground">
                      Popular
                    </span>
                  )}
                </div>
                <p className="mt-1 min-h-[3.75rem] text-sm text-muted-foreground">
                  {t.description}
                </p>
                <div className="mt-5 flex items-end gap-1">
                  <span className="text-[2rem] leading-none tabular-nums tracking-[-0.02em]">
                    {t.is_free ? "Free" : formatPrice(t.price_cents, t.currency)}
                  </span>
                  {!t.is_free && (
                    <span className="text-sm text-muted-foreground">/mo</span>
                  )}
                </div>
                <ul className="mt-6 flex-1 space-y-2.5 text-sm text-muted-foreground">
                  <PlanFeature>
                    {plural(t.monthly_applications, "application")} / mo
                  </PlanFeature>
                  <PlanFeature>
                    {plural(t.monthly_interviews, "mock interview")} / mo
                  </PlanFeature>
                  <PlanFeature>{t.prep_minutes} min interview prep</PlanFeature>
                </ul>
                {/* Carry the choice through signup instead of dropping it. */}
                <Link
                  href={`/register?plan=${encodeURIComponent(t.code)}`}
                  className={buttonClass(
                    t.is_featured ? "primary" : "secondary",
                    "md",
                    "mt-7 w-full",
                  )}
                >
                  {t.is_free ? "Start free" : `Choose ${t.name}`}
                </Link>
              </TiltCard>
            </RevealItem>
          ))}
        </Reveal>
      )}
    </section>
  );
}

function PlanFeature({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      <Check className="mt-0.5 h-4 w-4 shrink-0 text-subtle" aria-hidden />
      <span>{children}</span>
    </li>
  );
}
