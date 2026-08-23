"use client";

/**
 * The three components that make a screen recognisably Aptil.
 *
 * They exist because the product's whole promise is "something is happening
 * while you're away", and coloured status pills are a poor way to say that:
 * they're unscannable in a list, and they make state depend on colour alone.
 */

// --- pipeline model -------------------------------------------------------
// How far along the hiring pipeline each backend status sits. Used to fill the
// status rail; the text label always travels with it so the rail is redundant
// information, never the only signal.
const PROGRESS: Record<string, number> = {
  discovered: 0.1,
  matched: 0.2,
  queued: 0.35,
  applying: 0.45,
  submitted: 0.6,
  confirmed: 0.7,
  interview: 0.8,
  offer: 1,
  needs_info: 0.3,
  failed: 0.3,
  rejected: 1,
};

export type RailTone = "accent" | "warn" | "danger" | "quiet";

function toneFor(status: string): RailTone {
  if (status === "needs_info") return "warn";
  if (status === "failed") return "danger";
  if (status === "rejected") return "quiet";
  // Early stages are grey: nothing has actually happened yet, and colouring
  // them accent would make a page of "matched" rows look like progress.
  if (PROGRESS[status] !== undefined && PROGRESS[status] <= 0.2) return "quiet";
  return "accent";
}

const RAIL_BG: Record<RailTone, string> = {
  accent: "bg-accent",
  warn: "bg-warn",
  danger: "bg-danger",
  quiet: "bg-subtle",
};

/**
 * Signature component 1 — the status rail.
 *
 * A 2px hairline down the left edge of a row, filled to show how far this
 * application has travelled. The pipeline becomes readable by scanning one
 * edge instead of parsing a column of pills.
 *
 * The parent must be `relative` and `overflow-hidden` (or rounded to match).
 */
export function StatusRail({ status }: { status: string }) {
  const pct = Math.round((PROGRESS[status] ?? 0.1) * 100);
  const tone = toneFor(status);
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute inset-y-0 left-0 w-[2px] overflow-hidden rounded-l-xl bg-border"
    >
      <span
        className={`absolute bottom-0 left-0 w-full transition-[height] duration-200 ease-ease ${RAIL_BG[tone]}`}
        style={{ height: `${pct}%` }}
      />
    </span>
  );
}

/**
 * Signature component 2 — the score arc.
 *
 * Match quality as a thin arc around a tabular number: no coloured pill, no
 * progress bar. Grey below 70%, accent at 70%+, so a strong match is visible
 * at a glance without reading the digits. It is the only circular element on
 * the screen, which is what makes it a mark rather than a widget.
 */
export function ScoreArc({
  value,
  size = 40,
  label = "Match score",
  digits = 0,
  suffix = "%",
}: {
  /** 0–1. */
  value: number;
  size?: number;
  label?: string;
  digits?: number;
  suffix?: string;
}) {
  const clamped = Math.max(0, Math.min(1, value));
  const strong = clamped >= 0.7;
  const stroke = size >= 96 ? 3 : 2;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const shown = (clamped * 100).toFixed(digits);
  const textSize = size >= 96 ? "text-2xl" : size >= 56 ? "text-sm" : "text-xs";

  return (
    <span
      role="img"
      aria-label={`${label}: ${shown}${suffix === "%" ? " percent" : suffix}`}
      className="relative inline-grid shrink-0 place-items-center"
      style={{ width: size, height: size }}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="absolute inset-0 -rotate-90"
        aria-hidden
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          strokeWidth={stroke}
          className="stroke-border"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - clamped)}
          className={`transition-[stroke-dashoffset] duration-200 ease-ease ${
            strong ? "stroke-accent" : "stroke-subtle"
          }`}
        />
      </svg>
      <span
        aria-hidden
        className={`relative ${textSize} tabular-nums ${
          strong ? "text-accent" : "text-muted-foreground"
        }`}
      >
        {shown}
        {suffix}
      </span>
    </span>
  );
}

/**
 * Signature component 3 — the working line.
 *
 * A 1px accent hairline travelling across the top of the page whenever
 * background work is running. It replaces the spinner for work the user did
 * not synchronously request, which is most of what this product does.
 *
 * Announcing is separate from showing: the visual is aria-hidden and the
 * status text is polite, so a screen reader hears "Searching for matches"
 * once rather than every animation frame.
 */
export function WorkingLine({
  active,
  label = "Working",
}: {
  active: boolean;
  label?: string;
}) {
  return (
    <>
      <div
        aria-hidden
        className={`pointer-events-none fixed inset-x-0 top-0 z-50 h-px overflow-hidden transition-opacity duration-200 ease-ease ${
          active ? "opacity-100" : "opacity-0"
        }`}
      >
        {active && (
          <div className="h-px w-1/3 animate-working-line bg-gradient-to-r from-transparent via-accent to-transparent" />
        )}
      </div>
      <span role="status" className="sr-only">
        {active ? label : ""}
      </span>
    </>
  );
}

/**
 * A `needs_info` row is progress that stalled, not a failure — so show what
 * Aptil already filled in as completed ticks before asking for the last bit.
 */
export function StalledTicks({
  done,
  total,
  label,
}: {
  done: number;
  total: number;
  label: string;
}) {
  return (
    <span className="inline-flex items-center gap-[2px]" title={label}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          aria-hidden
          className={`h-1 w-3 rounded-sm ${i < done ? "bg-subtle" : "bg-border"}`}
        />
      ))}
    </span>
  );
}
