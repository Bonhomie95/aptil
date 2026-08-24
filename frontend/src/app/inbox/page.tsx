"use client";

import { useEffect, useMemo, useState } from "react";
import { Mail } from "lucide-react";
import { AppShell, PageHeader } from "@/components/app-shell";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { useSession } from "@/hooks/use-session";
import { Pagination } from "@/components/pagination";
import { api, type InboxItem } from "@/lib/api";

/**
 * Inbox — the full history of what employers and job sites sent back.
 *
 * Every account Aptil creates uses the user's managed alias, so verification
 * links, "application received" confirmations, interview invites and rejections
 * all land here. This is the reply history in one place, separate from the
 * pipeline on the dashboard.
 */

const KIND: Record<InboxItem["kind"], { label: string; className: string }> = {
  interview: {
    label: "Interview",
    className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  },
  confirmation: {
    label: "Application received",
    className: "bg-accent/10 text-accent",
  },
  rejection: {
    label: "Not moving forward",
    className: "bg-muted text-muted-foreground",
  },
  verification: {
    label: "Verifying account",
    className: "bg-muted text-muted-foreground",
  },
  other: { label: "Update", className: "bg-muted text-muted-foreground" },
};

const FILTERS: { key: "all" | InboxItem["kind"]; label: string }[] = [
  { key: "all", label: "All" },
  { key: "interview", label: "Interviews" },
  { key: "confirmation", label: "Confirmations" },
  { key: "rejection", label: "Rejections" },
  { key: "other", label: "Other" },
];

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function InboxPage() {
  const { user, loading: sessionLoading, error: sessionError, retry } =
    useSession();
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | InboxItem["kind"]>("all");
  const [openId, setOpenId] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [perPage, setPerPage] = useState(25);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const rows = await api.inbox(perPage, page * perPage);
        if (!cancelled) setItems(rows);
      } catch (err) {
        if (!cancelled)
          setError(
            err instanceof Error ? err.message : "Couldn't load your inbox.",
          );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, page, perPage]);

  const shown = useMemo(
    () => (items ?? []).filter((m) => filter === "all" || m.kind === filter),
    [items, filter],
  );

  if (sessionLoading) {
    return (
      <AppShell>
        <Skeleton className="mx-auto h-10 w-48" />
        <Skeleton className="mx-auto mt-8 h-64 max-w-3xl" />
      </AppShell>
    );
  }
  if (sessionError) {
    return (
      <AppShell>
        <ErrorState
          message={sessionError}
          onRetry={retry}
          className="mx-auto max-w-xl"
        />
      </AppShell>
    );
  }

  return (
    <AppShell email={user?.email}>
      <PageHeader
        title="Inbox"
        description="Replies from employers and job sites — confirmations, interview invites, and more — collected from your applications automatically."
      />

      {error ? (
        <ErrorState
          message={error}
          onRetry={() => location.reload()}
          className="mt-8"
        />
      ) : items === null ? (
        <div className="mt-8 space-y-3">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="mt-8 rounded-xl border border-border bg-card">
          <EmptyState
            title="No replies yet"
            body="When employers or job sites respond to your applications, their messages show up here automatically — you never have to forward anything."
          />
        </div>
      ) : (
        <div className="mt-6">
          <div className="mb-4 flex flex-wrap gap-2">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                aria-pressed={filter === f.key}
                className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${
                  filter === f.key
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-border text-muted-foreground hover:border-accent/40"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>

          <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
            {shown.map((m) => {
              const k = KIND[m.kind];
              const open = openId === m.id;
              return (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() => setOpenId(open ? null : m.id)}
                    className="flex w-full items-start gap-3 px-5 py-4 text-left transition-colors hover:bg-muted/40"
                  >
                    <Mail
                      className="mt-0.5 h-4 w-4 shrink-0 text-subtle"
                      aria-hidden
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`rounded px-1.5 py-0.5 text-xs font-medium ${k.className}`}
                        >
                          {k.label}
                        </span>
                        <span className="truncate text-sm text-muted-foreground">
                          {m.sender_domain}
                        </span>
                        <span className="ml-auto shrink-0 text-xs text-subtle">
                          {when(m.received_at)}
                        </span>
                      </div>
                      <p className="mt-1 truncate text-sm font-medium">
                        {m.subject || "(no subject)"}
                      </p>
                      {open && (
                        <p className="mt-3 whitespace-pre-wrap text-sm text-muted-foreground">
                          {m.body_text || "(no message body)"}
                        </p>
                      )}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
          {shown.length === 0 && (
            <p className="mt-6 text-center text-sm text-muted-foreground">
              Nothing in this category yet.
            </p>
          )}
          <Pagination
            page={page}
            perPage={perPage}
            count={items.length}
            onPage={setPage}
            onPerPage={(n) => {
              setPerPage(n);
              setPage(0);
            }}
          />
        </div>
      )}
    </AppShell>
  );
}
