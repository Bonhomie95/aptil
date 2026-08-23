/** Formatting helpers shared by the marketing and in-app surfaces. */

/** Render a price in the plan's own currency rather than assuming dollars. */
export function formatPrice(cents: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: currency || "USD",
      // Show cents only when the price actually has them, so $19.50 does not
      // round to $20 but $19.00 still renders as $19.
      minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(cents / 100);
  } catch {
    return `${(cents / 100).toFixed(cents % 100 === 0 ? 0 : 2)} ${currency}`;
  }
}

/** Human-readable salary range, or null when the posting gave no figures. */
export function formatSalary(
  min: number | null,
  max: number | null,
  currency: string | null,
): string | null {
  if (min == null && max == null) return null;
  const fmt = (n: number) => {
    try {
      return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: currency || "USD",
        maximumFractionDigits: 0,
      }).format(n);
    } catch {
      return `${n.toLocaleString()} ${currency ?? ""}`.trim();
    }
  };
  if (min != null && max != null) return `${fmt(min)} – ${fmt(max)}`;
  return fmt((min ?? max)!);
}

/** "3 days ago" style relative time for posting dates. */
export function relativeTime(iso: string | null): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const days = Math.round((Date.now() - then) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  const months = Math.round(days / 30);
  return months === 1 ? "a month ago" : `${months} months ago`;
}

/** Pluralise a countable noun: 1 application, 2 applications. */
export function plural(count: number, singular: string, pluralForm?: string): string {
  const word = count === 1 ? singular : (pluralForm ?? `${singular}s`);
  return `${count} ${word}`;
}

/**
 * "Remote" is both a location and a flag, and a posting can carry it twice.
 * Saying it once is the whole job.
 */
export function locationLine(
  location: string | null | undefined,
  remote: boolean | null | undefined,
): string {
  const loc = location?.trim() ?? "";
  const saysRemote = /remote/i.test(loc);
  const parts = [loc, remote && !saysRemote ? "Remote" : ""].filter(Boolean);
  return parts.join(" • ");
}
