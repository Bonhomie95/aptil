"use client";

import { useEffect, useState } from "react";
import { Inbox as InboxIcon, Mail } from "lucide-react";
import { api, type InboxItem } from "@/lib/api";

/**
 * Employer replies, shown on the dashboard.
 *
 * Because accounts we create use the user's managed alias, everything a site or
 * employer sends — verification, "application received", interview invites,
 * rejections — arrives centrally and becomes visible status the user never has
 * to forward to us. This card is that window.
 */

const KIND_STYLE: Record<
  InboxItem["kind"],
  { label: string; className: string }
> = {
  verification: {
    label: "Verifying account",
    className: "bg-muted text-muted-foreground",
  },
  confirmation: {
    label: "Application received",
    className: "bg-accent/10 text-accent",
  },
  interview: {
    label: "Interview",
    className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  },
  rejection: {
    label: "Not moving forward",
    className: "bg-muted text-muted-foreground",
  },
  other: { label: "Update", className: "bg-muted text-muted-foreground" },
};

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export function ApplyInbox() {
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await api.inbox(15);
        if (!cancelled) setItems(rows);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // The feature is optional per deployment; if the endpoint 404s or the inbox
  // is simply empty, render nothing rather than an empty shell.
  if (failed || (items !== null && items.length === 0)) return null;

  return (
    <section className="rounded-xl border border-border bg-card">
      <header className="flex items-center gap-2 border-b border-border px-5 py-4">
        <InboxIcon className="h-4 w-4 text-subtle" aria-hidden />
        <h2 className="text-sm font-medium">Replies from employers</h2>
      </header>
      <ul className="divide-y divide-border">
        {items === null
          ? [0, 1, 2].map((i) => (
              <li key={i} className="h-16 animate-pulse bg-muted/30" />
            ))
          : items.map((m) => {
              const style = KIND_STYLE[m.kind];
              return (
                <li key={m.id} className="flex gap-3 px-5 py-4">
                  <Mail
                    className="mt-0.5 h-4 w-4 shrink-0 text-subtle"
                    aria-hidden
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded px-1.5 py-0.5 text-xs font-medium ${style.className}`}
                      >
                        {style.label}
                      </span>
                      <span className="truncate text-sm text-muted-foreground">
                        {m.sender_domain}
                      </span>
                      <span className="ml-auto shrink-0 text-xs text-subtle">
                        {timeAgo(m.received_at)}
                      </span>
                    </div>
                    <p className="mt-1 truncate text-sm font-medium">
                      {m.subject || "(no subject)"}
                    </p>
                  </div>
                </li>
              );
            })}
      </ul>
    </section>
  );
}
