import Link from "next/link";
import { buttonClass } from "@/components/button-styles";
import { ScoreArc, StatusRail } from "@/components/signals";
import { TiltCard } from "@/components/tilt-card";

/**
 * The hero states what the product does and for whom, then shows the two
 * components that carry the product's argument — the status rail and the
 * score arc — rather than describing them with adjectives.
 *
 * The headline itself still renders with no entrance animation — the first
 * thing on the page is the thing the visitor came for, and any animation
 * here is one paused-rAF away from a blank hero. Below it: a restrained
 * ambient glow (a single radial wash, not a gradient panel) and cards that
 * tilt toward the pointer, giving the page a sense of physical depth without
 * fabricating any of the numbers on them.
 */
export function Hero() {
  return (
    <section className="relative px-4 pb-16 pt-28 sm:pt-36 lg:px-8">
      <div
        aria-hidden
        className="hero-glow pointer-events-none absolute inset-x-0 top-0 -z-10 h-[600px]"
      />
      <div className="mx-auto max-w-[1200px]">
        <div className="mx-auto max-w-3xl text-center">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">
            Discover. Tailor. Apply. Prep.
          </p>

          <h1
            className="mt-4 font-display text-[2.75rem] leading-[1.06] tracking-[-0.025em] sm:text-6xl"
          >
            Land the job. Ace the interview.
          </h1>

          <p
            className="mx-auto mt-6 max-w-xl text-base text-muted-foreground sm:text-lg sm:leading-7"
          >
            Aptil finds roles that fit, tailors your résumé, and applies through
            official channels — then preps you to ace the interview, grounded in
            your real CV and the exact job you&apos;re targeting.
          </p>

          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row sm:gap-4">
            <Link href="/register" className={buttonClass("primary", "lg")}>
              Start structuring your search
            </Link>
            <p className="text-xs text-muted-foreground">
              Free plan, no credit card. Export or delete your data anytime.
            </p>
          </div>
        </div>

        <div className="mt-16">
          <ProofGrid />
        </div>
      </div>
    </section>
  );
}

// Illustrative, not live data — said out loud rather than implied, because a
// fabricated "128 applications this week" is exactly the kind of thing this
// product must never do.
const ROWS: [string, string, string, string][] = [
  ["Acme Corp", "Senior Engineer", "offer", "Offer"],
  ["Global Tech", "Product Manager", "interview", "Interview"],
  ["Stark Ind.", "Data Analyst", "submitted", "Submitted"],
];

function ProofGrid() {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <TiltCard className="rounded-xl border border-border/40 bg-card p-6 sm:p-8 lg:col-span-1">
        <h2 className="text-xl tracking-[-0.01em] sm:text-2xl">Application pipeline</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          One hairline down each row shows how far it has travelled. Readable by
          scanning an edge — no kanban board to maintain.
        </p>
        <ul className="mt-6 space-y-3" aria-label="Example pipeline rows">
          {ROWS.map(([company, role, status, label]) => (
            <li
              key={company}
              className="relative flex items-center gap-4 overflow-hidden rounded-lg bg-muted p-2 pl-4"
            >
              <StatusRail status={status} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm">{company}</div>
                <div className="truncate text-xs text-muted-foreground">{role}</div>
              </div>
              <span className="shrink-0 rounded-sm bg-tile px-2 py-0.5 text-xs uppercase tracking-[0.03em]">
                {label}
              </span>
            </li>
          ))}
        </ul>
      </TiltCard>

      <TiltCard className="rounded-xl border border-border/40 bg-card p-6 sm:p-8 lg:col-span-2">
        <h2 className="text-xl tracking-[-0.01em] sm:text-2xl">Actionable metrics</h2>
        <p className="mt-2 max-w-md text-sm text-muted-foreground">
          Every match carries the reasoning behind it, so you can tell a weak
          application from a slow employer.
        </p>
        <div className="mt-8 flex flex-col gap-6 sm:flex-row sm:items-center">
          <Metric value={0.82} label="Response rate" note="Up 12% this week" />
          <div className="sm:border-l sm:border-border sm:pl-6">
            <Metric value={0.45} label="Interview conversion" note="Needs attention" />
          </div>
        </div>
        <p className="mt-8 text-xs text-subtle">Sample figures, shown to illustrate the interface.</p>
      </TiltCard>
    </div>
  );
}

function Metric({
  value,
  label,
  note,
}: {
  value: number;
  label: string;
  note: string;
}) {
  return (
    <div className="flex items-center gap-4">
      <ScoreArc value={value} size={64} label={label} />
      <div>
        <p className="text-xs uppercase tracking-[0.05em] text-muted-foreground">
          {label}
        </p>
        <p className="mt-1 text-base">{note}</p>
      </div>
    </div>
  );
}
