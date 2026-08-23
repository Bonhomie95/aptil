"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

/**
 * Where the user wants jobs — continents and/or individual countries.
 *
 * Selecting a continent stores the continent code (e.g. "europe"); the backend
 * expands it to every country it covers. This is also how a user EXCLUDES
 * places: whatever isn't selected isn't searched. Empty selection = fall back
 * to their home country.
 *
 * The option list comes from /jobs/search-locations, which is driven by what
 * the aggregator actually serves, so we can never offer a dead location.
 */

type Locations = {
  countries: { code: string; name: string }[];
  continents: { code: string; name: string; countries: string[] }[];
};

export function LocationPicker({
  value,
  onChange,
}: {
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const [opts, setOpts] = useState<Locations | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.searchLocations();
        if (!cancelled) setOpts(data);
      } catch {
        if (!cancelled) setOpts({ countries: [], continents: [] });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function toggle(code: string) {
    onChange(
      value.includes(code)
        ? value.filter((c) => c !== code)
        : [...value, code],
    );
  }

  if (!opts) return <div className="h-24 animate-pulse rounded-lg bg-muted/30" />;

  return (
    <div className="space-y-4">
      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-subtle">
          Whole regions
        </p>
        <div className="flex flex-wrap gap-2">
          {opts.continents.map((c) => (
            <Chip
              key={c.code}
              active={value.includes(c.code)}
              onClick={() => toggle(c.code)}
            >
              {c.name}
            </Chip>
          ))}
        </div>
      </div>
      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-subtle">
          Or specific countries
        </p>
        <div className="flex flex-wrap gap-2">
          {opts.countries.map((c) => (
            <Chip
              key={c.code}
              active={value.includes(c.code)}
              onClick={() => toggle(c.code)}
            >
              {c.name}
            </Chip>
          ))}
        </div>
      </div>
      {value.length === 0 && (
        <p className="text-xs text-muted-foreground">
          Nothing selected — we&apos;ll search jobs in your home country.
        </p>
      )}
    </div>
  );
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${
        active
          ? "border-accent bg-accent/10 text-accent"
          : "border-border text-muted-foreground hover:border-accent/40"
      }`}
    >
      {children}
    </button>
  );
}
