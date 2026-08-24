"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

/**
 * Pager for list pages: Prev/Next + a per-page selector.
 *
 * The backend list endpoints return a page of rows without a total count, so
 * "there is a next page" is inferred from a full page (rows === perPage).
 * That's honest — we never claim a page number we can't back up.
 */

export const PER_PAGE_OPTIONS = [10, 25, 50, 100] as const;

export function Pagination({
  page,
  perPage,
  count,
  onPage,
  onPerPage,
  busy,
}: {
  /** 0-based current page. */
  page: number;
  perPage: number;
  /** Rows returned for the current page. */
  count: number;
  onPage: (next: number) => void;
  onPerPage: (n: number) => void;
  busy?: boolean;
}) {
  const hasPrev = page > 0;
  const hasNext = count === perPage; // a full page implies more may follow
  const from = count === 0 ? 0 : page * perPage + 1;
  const to = page * perPage + count;

  return (
    <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span>
          {from}–{to}
        </span>
        <label className="ml-2 flex items-center gap-1.5">
          <span className="text-xs">Per page</span>
          <select
            aria-label="Results per page"
            value={perPage}
            onChange={(e) => onPerPage(Number(e.target.value))}
            className="h-8 rounded-lg border border-border bg-card px-2 text-sm outline-none focus:border-accent"
          >
            {PER_PAGE_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onPage(page - 1)}
          disabled={!hasPrev || busy}
          className="flex h-9 items-center gap-1 rounded-lg border border-border px-3 text-sm transition-colors enabled:hover:bg-muted/40 disabled:opacity-40"
        >
          <ChevronLeft className="h-4 w-4" aria-hidden />
          Prev
        </button>
        <span className="text-sm text-muted-foreground">Page {page + 1}</span>
        <button
          type="button"
          onClick={() => onPage(page + 1)}
          disabled={!hasNext || busy}
          className="flex h-9 items-center gap-1 rounded-lg border border-border px-3 text-sm transition-colors enabled:hover:bg-muted/40 disabled:opacity-40"
        >
          Next
          <ChevronRight className="h-4 w-4" aria-hidden />
        </button>
      </div>
    </div>
  );
}
