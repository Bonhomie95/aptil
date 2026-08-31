"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ExternalLink, Pause, Play, RefreshCw, Send, Square } from "lucide-react";
import { AppShell, PageHeader } from "@/components/app-shell";
import { ScoreArc, StalledTicks, StatusRail } from "@/components/signals";
import { ApplyInbox } from "@/components/apply-inbox";
import {
  Button,
  EmptyState,
  ErrorState,
  Notice,
  Skeleton,
  StateLabel,
  buttonClass,
} from "@/components/ui";
import { useSession } from "@/hooks/use-session";
import { locationLine } from "@/lib/format";
import {
  api,
  type Application,
  type AutomationState,
  type AutomationStatus,
  type Subscription,
} from "@/lib/api";

type Stats = {
  by_status: Record<string, number>;
  total: number;
  applications_used: number;
};

// The pipeline moves in the background, so poll rather than showing a snapshot
// that silently goes stale (the copy promises a live view).
const POLL_MS = 20_000;
// Only while a search is actually running — see the effect below.
const SEARCH_POLL_MS = 4_000;

// Turns the engine's machine-readable reason into a next step the user can act
// on, instead of a uniform "needs your attention".
const NEEDS_ACTION_COPY: Record<string, string> = {
  finish_manually:
    "This employer's form needs a human — open it and submit the last step. Your details are already filled in.",
  verify_manually:
    "We submitted it but the site never confirmed. Open it to check whether it went through.",
  retry_later:
    "The apply engine was unavailable. This will be retried automatically.",
  upgrade: "You've used this period's applications. Upgrade for more.",
  // Sites that hide the application form behind a sign-in. We never create an
  // account, so the user has to make one and store it first.
  add_credential:
    "This site won't show the form until you're signed in. Create an account there, then save it under Settings → Job site accounts and we'll use it.",
  check_credential:
    "We couldn't sign in with the account you saved for this site. Check it under Settings → Job site accounts — the password may have changed, or the site may be asking for a second factor.",
  finish_multi_step:
    "This employer uses a multi-page application we can't complete for you. Open it and work through the steps — your profile details are ready to paste.",
  // Not a failure: the employer routed us to their own careers site, which has
  // its own form we have no selectors for. Saying so beats "we couldn't read
  // the form", which sounds like something is broken.
  apply_on_employer_site:
    "This employer takes applications on their own careers site rather than through their job board, so we can't fill it for you. Open it and apply there — your profile details are ready to paste.",
  review: "Open the posting to finish this application.",
};

const NEEDS_ACTION_SHORT: Record<string, string> = {
  finish_manually: "Finish on the employer's form",
  verify_manually: "Confirm it went through",
  retry_later: "Will retry automatically",
  upgrade: "Application quota reached",
  add_credential: "Needs a site account",
  check_credential: "Sign-in didn't work",
  finish_multi_step: "Multi-page application",
  apply_on_employer_site: "Employer's own site",
  review: "Needs a last step",
};

function label(status: string) {
  return status.replace(/_/g, " ");
}

// Human copy for an application's event trail (JobApplication.events —
// "kind" is either a lifecycle step or the ATS adapter's outcome string).
// Anything unmapped falls back to a de-slugged version of the kind itself,
// so a new outcome the copy hasn't caught up to still reads reasonably.
const EVENT_LABEL: Record<string, string> = {
  queued: "Queued for submission",
  requeued: "Re-queued",
  apply_started: "Started filling out the application",
  submitted: "Submitted",
  needs_info: "Paused — needs your input",
  failed: "Failed",
  verification_pending: "Waiting on email verification for the new account",
  ...NEEDS_ACTION_SHORT,
};

function eventLabel(kind: string) {
  return EVENT_LABEL[kind] ?? label(kind);
}

function eventTime(at: string) {
  const d = new Date(at);
  return Number.isNaN(d.getTime())
    ? at
    : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// Rows whose real-world outcome the user tracks by hand.
const EDITABLE = ["submitted", "confirmed", "interview"];

// What the API will actually accept (jobs.USER_SETTABLE_STATUSES). "Submitted"
// is absent on purpose: only the engine may claim an application was sent, and
// only once the employer's page confirms it. Offering it here produced a 422
// on a choice the UI had just presented.
const SETTABLE: [string, string][] = [
  ["confirmed", "Confirmed"],
  ["interview", "Interviewing"],
  ["offer", "Offer"],
  ["rejected", "Rejected"],
];

const STATUS_LABEL: Record<string, string> = {
  submitted: "Submitted",
  confirmed: "Confirmed",
  interview: "Interviewing",
  offer: "Offer",
  rejected: "Rejected",
};

export default function DashboardPage() {
  const { user, loading: sessionLoading, error: sessionError, retry } = useSession({
    requireOnboarded: true,
  });
  const [stats, setStats] = useState<Stats | null>(null);
  const [apps, setApps] = useState<Application[] | null>(null);
  const [sub, setSub] = useState<Subscription | null>(null);
  const [dataError, setDataError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [matching, setMatching] = useState(false);
  const [searching, setSearching] = useState(false);
  const [automation, setAutomation] = useState<AutomationStatus | null>(null);
  const [automationBusy, setAutomationBusy] = useState(false);
  const [applyingBatch, setApplyingBatch] = useState(false);
  const [tab, setTab] = useState<"matches" | "applied">("matches");
  const [filterStatus, setFilterStatus] = useState("all"); // sub-filter (Applied)
  const [filterLocation, setFilterLocation] = useState("");
  const [sortBy, setSortBy] = useState<"score" | "recent">("score");
  const [stopping, setStopping] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const loadData = useCallback(async (quiet = false) => {
    if (!quiet) setDataError(null);
    try {
      const [s, a, b, auto] = await Promise.all([
        api.stats(),
        api.applications(),
        api.subscription(),
        api.getAutomation(),
      ]);
      setStats(s);
      setApps(a);
      setSub(b);
      setAutomation(auto);
      setDataError(null);
    } catch (err) {
      // A background refresh failing shouldn't wipe what's already on screen.
      if (!quiet) {
        setDataError(
          err instanceof Error ? err.message : "Couldn't load your pipeline.",
        );
      }
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;

    // Inlined rather than calling loadData() directly: the first state update
    // must land after the await, not synchronously inside the effect.
    const refresh = async (quiet: boolean) => {
      try {
        const [s, a, b] = await Promise.all([
          api.stats(),
          api.applications(),
          api.subscription(),
        ]);
        if (cancelled) return;
        setStats(s);
        setApps(a);
        setSub(b);
        setDataError(null);
      } catch (err) {
        if (cancelled || quiet) return;
        setDataError(
          err instanceof Error ? err.message : "Couldn't load your pipeline.",
        );
      }
    };

    const pollStatus = async () => {
      try {
        const s = await api.matchingStatus();
        if (!cancelled) setSearching(s.running);
      } catch {
        // Status is advisory; a failure here must not disturb the page.
      }
    };

    refresh(false);
    pollStatus();
    const id = setInterval(() => refresh(true), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [user]);

  // The fast tick exists to flip the button back the moment a search ends, so
  // it only runs while one IS running. Unconditionally it was 900 requests an
  // hour from every open tab, almost all of them answering "no, nothing".
  useEffect(() => {
    if (!user || !searching) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const s = await api.matchingStatus();
        if (!cancelled) setSearching(s.running);
      } catch {
        // Status is advisory; a failure here must not disturb the page.
      }
    };
    const id = setInterval(tick, SEARCH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [user, searching]);

  async function applyTop(count: number) {
    setApplyingBatch(true);
    setNotice(null);
    try {
      const res = await api.applyBatch(count);
      setNotice(res.detail ?? `Queued ${res.queued} for submission.`);
      await loadData(true);
    } catch (err) {
      setNotice(
        err instanceof Error ? err.message : "Couldn't queue that batch.",
      );
    } finally {
      setApplyingBatch(false);
    }
  }

  async function runMatching() {
    setMatching(true);
    setNotice(null);
    try {
      const res = await api.requestMatching();
      setNotice(res.detail ?? "Matching started.");
      setSearching(true);
      setTimeout(() => loadData(true), 4000);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Couldn't start matching.");
    } finally {
      setMatching(false);
    }
  }

  async function stopMatching() {
    setStopping(true);
    try {
      const res = await api.cancelMatching();
      setNotice(res.detail ?? "Search stopped.");
      setSearching(false);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Couldn't stop the search.");
    } finally {
      setStopping(false);
    }
  }

  async function applyNow(id: string) {
    setBusyId(id);
    setNotice(null);
    try {
      const res = await api.applyNow(id);
      setNotice(res.detail ?? "Queued.");
      await loadData(true);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Couldn't queue that application.");
    } finally {
      setBusyId(null);
    }
  }

  async function setStatus(id: string, status: string) {
    setBusyId(id);
    try {
      const updated = await api.updateApplicationStatus(id, status);
      setApps((cur) => (cur ?? []).map((a) => (a.id === id ? updated : a)));
      await loadData(true);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Couldn't update that.");
    } finally {
      setBusyId(null);
    }
  }

  if (sessionLoading) {
    return (
      <AppShell>
        <Skeleton className="h-10 w-52" />
        <div className="mt-8 grid gap-6 lg:grid-cols-3">
          <div className="space-y-3 lg:col-span-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
          <Skeleton className="h-48" />
        </div>
      </AppShell>
    );
  }

  if (sessionError) {
    return (
      <AppShell>
        <ErrorState message={sessionError} onRetry={retry} className="mx-auto max-w-xl" />
      </AppShell>
    );
  }

  async function changeAutomation(next: AutomationState) {
    setAutomationBusy(true);
    setNotice(null);
    try {
      const status = await api.setAutomation(next);
      setAutomation(status);
      setNotice(
        next === "running"
          ? "Search resumed. New matches will start appearing shortly."
          : next === "paused"
            ? status.queued > 0
              ? `Search paused. ${status.queued} application${status.queued === 1 ? "" : "s"} already queued will still go out — stop instead if you want those cancelled.`
              : "Search paused. Nothing new will be applied for until you resume."
            : "Search stopped and anything queued was cancelled. Nothing further will be submitted in your name.",
      );
    } catch (err) {
      setNotice(
        err instanceof Error ? err.message : "Couldn't change the search state.",
      );
    } finally {
      setAutomationBusy(false);
    }
  }

  const matchedCount =
    apps?.filter((a) => a.status === "matched").length ?? 0;

  // Two views over the same pipeline: jobs matched but not yet a completed
  // application ("Matches"), and everything that has actually gone out or has an
  // outcome ("Applied"). Both filter + sort CLIENT-SIDE, so changing them
  // reorders the current list instantly — no re-search.
  const MATCHES_STATUSES = ["matched", "queued"];
  // needs_info/failed are attempts the engine made and could not finish or
  // that failed outright — they belong here, with a reason, not hidden.
  const APPLIED_STATUSES = [
    "submitted", "confirmed", "interview", "offer", "rejected",
    "needs_info", "failed",
  ];
  const all = apps ?? [];
  const matchesCount = all.filter((a) => MATCHES_STATUSES.includes(a.status)).length;
  const appliedCount = all.filter((a) => APPLIED_STATUSES.includes(a.status)).length;
  const groupStatuses = tab === "matches" ? MATCHES_STATUSES : APPLIED_STATUSES;

  const visibleApps = all
    .filter((a) => groupStatuses.includes(a.status))
    .filter((a) => tab === "matches" || filterStatus === "all" || a.status === filterStatus)
    .filter((a) => {
      const q = filterLocation.trim().toLowerCase();
      if (!q) return true;
      return (a.job?.location ?? "").toLowerCase().includes(q);
    })
    .slice()
    .sort((x, y) =>
      sortBy === "recent"
        ? (y.created_at ?? "").localeCompare(x.created_at ?? "")
        : (y.match_score ?? 0) - (x.match_score ?? 0),
    );

  const openCount =
    apps?.filter((a) => !["rejected", "failed"].includes(a.status)).length ?? 0;

  return (
    <AppShell
      email={user?.email}
      working={searching}
      workingLabel="Searching for new matches"
    >
      <PageHeader
        title="Your pipeline"
        description={
          apps === null || openCount === 0
            ? "Everything Aptil is doing for you. Refreshes automatically."
            : `Tracking ${openCount} ongoing ${openCount === 1 ? "opportunity" : "opportunities"}. Refreshes automatically.`
        }
        actions={
          searching ? (
            <>
              <span className="text-sm text-muted-foreground">Searching…</span>
              <Button variant="danger" onClick={stopMatching} loading={stopping}>
                {!stopping && <Square className="h-3.5 w-3.5" aria-hidden />}
                Stop
              </Button>
            </>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              {matchedCount > 0 && (
                <>
                  <Button
                    onClick={() => applyTop(5)}
                    loading={applyingBatch}
                    disabled={applyingBatch}
                  >
                    {!applyingBatch && <Send className="h-4 w-4" aria-hidden />}
                    Apply top 5
                  </Button>
                  {matchedCount > 5 && (
                    <Button
                      variant="secondary"
                      onClick={() => applyTop(10)}
                      loading={applyingBatch}
                      disabled={applyingBatch}
                    >
                      Apply top 10
                    </Button>
                  )}
                </>
              )}
              <Button variant="secondary" onClick={runMatching} loading={matching}>
                {!matching && <RefreshCw className="h-4 w-4" aria-hidden />}
                Find new matches
              </Button>
            </div>
          )
        }
      />

      {notice && <Notice className="mt-6">{notice}</Notice>}

      {/* The engine applies in the user's name, so the off switch lives on the
          main screen, not behind a settings menu. Someone who just accepted an
          offer needs to find it in one look. */}
      {automation && (
        <section
          aria-label="Search status"
          className={`mt-6 flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl border p-4 ${
            automation.state === "running"
              ? "border-border bg-card"
              : "border-accent/40 bg-accent/5"
          }`}
        >
          <span className="flex items-center gap-2.5 text-sm font-medium">
            <span
              aria-hidden
              className={`h-2 w-2 shrink-0 rounded-full ${
                automation.state === "running"
                  ? "bg-accent motion-safe:animate-pulse"
                  : "bg-muted-foreground"
              }`}
            />
            {automation.state === "running"
              ? "Search is running"
              : automation.state === "paused"
                ? "Search is paused"
                : "Search is stopped"}
          </span>

          <p className="min-w-0 flex-1 text-sm text-muted-foreground">
            {automation.state === "running"
              ? "Aptil is finding matches and applying for you automatically."
              : automation.state === "paused"
                ? automation.queued > 0
                  ? `Nothing new will be applied for. ${automation.queued} application${automation.queued === 1 ? "" : "s"} queued before you paused will still go out.`
                  : "Nothing new will be applied for until you resume."
                : "No further applications will be submitted in your name."}
          </p>

          <div className="flex shrink-0 flex-wrap gap-2">
            {automation.state === "running" ? (
              <>
                <Button
                  variant="secondary"
                  onClick={() => changeAutomation("paused")}
                  loading={automationBusy}
                >
                  {!automationBusy && <Pause className="h-3.5 w-3.5" aria-hidden />}
                  Pause
                </Button>
                <Button
                  variant="danger"
                  onClick={() => changeAutomation("stopped")}
                  loading={automationBusy}
                >
                  {!automationBusy && <Square className="h-3.5 w-3.5" aria-hidden />}
                  Stop
                </Button>
              </>
            ) : (
              <>
                <Button
                  onClick={() => changeAutomation("running")}
                  loading={automationBusy}
                >
                  {!automationBusy && <Play className="h-3.5 w-3.5" aria-hidden />}
                  {automation.state === "paused" ? "Resume" : "Start again"}
                </Button>
                {automation.state === "paused" && (
                  <Button
                    variant="danger"
                    onClick={() => changeAutomation("stopped")}
                    loading={automationBusy}
                  >
                    {!automationBusy && <Square className="h-3.5 w-3.5" aria-hidden />}
                    Stop
                  </Button>
                )}
              </>
            )}
          </div>
        </section>
      )}

      <div className="mt-8 grid gap-6 lg:grid-cols-3">
        {/* Pipeline — 2/3 */}
        <div className="min-w-0 lg:col-span-2">
          <h2 className="sr-only">Applications</h2>
          {dataError ? (
            <ErrorState message={dataError} onRetry={() => loadData()} />
          ) : apps === null ? (
            <div className="space-y-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-20" />
              ))}
            </div>
          ) : apps.length === 0 ? (
            <div className="rounded-xl border border-border bg-card">
              <EmptyState
                title="No applications yet"
                body="Once your profile is complete, Aptil matches you to roles and applies on your behalf. You can also kick off a match run right now."
                action={
                  <Button onClick={runMatching} loading={matching}>
                    {!matching && <RefreshCw className="h-4 w-4" aria-hidden />}
                    Find matches now
                  </Button>
                }
              />
            </div>
          ) : (
            <>
              <div
                role="tablist"
                aria-label="Pipeline view"
                className="mb-4 flex gap-1 rounded-lg border border-border bg-card p-1"
              >
                {([
                  ["matches", "Matches", matchesCount],
                  ["applied", "Applied", appliedCount],
                ] as const).map(([key, lbl, n]) => (
                  <button
                    key={key}
                    role="tab"
                    aria-selected={tab === key}
                    onClick={() => {
                      setTab(key);
                      setFilterStatus("all");
                    }}
                    className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                      tab === key
                        ? "bg-accent/10 text-accent"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {lbl} <span className="tabular-nums opacity-70">({n})</span>
                  </button>
                ))}
              </div>

              <div className="mb-4 flex flex-wrap items-center gap-2">
                {tab === "applied" && (
                  <select
                    aria-label="Filter by status"
                    value={filterStatus}
                    onChange={(e) => setFilterStatus(e.target.value)}
                    className="h-9 rounded-lg border border-border bg-card px-3 text-sm outline-none focus:border-accent"
                  >
                    <option value="all">All applied</option>
                    <option value="submitted">Submitted</option>
                    <option value="interview">Interview</option>
                    <option value="offer">Offer</option>
                    <option value="rejected">Rejected</option>
                    <option value="needs_info">Needs your action</option>
                    <option value="failed">Failed</option>
                  </select>
                )}
                <select
                  aria-label="Sort by"
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as "score" | "recent")}
                  className="h-9 rounded-lg border border-border bg-card px-3 text-sm outline-none focus:border-accent"
                >
                  <option value="score">Best match</option>
                  <option value="recent">Most recent</option>
                </select>
                <input
                  aria-label="Filter by location"
                  value={filterLocation}
                  onChange={(e) => setFilterLocation(e.target.value)}
                  placeholder="Filter location (e.g. US, Remote)"
                  className="h-9 flex-1 min-w-[10rem] rounded-lg border border-border bg-card px-3 text-sm outline-none placeholder:text-subtle focus:border-accent"
                />
                {(filterStatus !== "all" || filterLocation) && (
                  <button
                    type="button"
                    onClick={() => {
                      setFilterStatus("all");
                      setFilterLocation("");
                    }}
                    className="text-sm text-accent underline-offset-4 hover:underline"
                  >
                    Clear
                  </button>
                )}
              </div>
              {visibleApps.length === 0 ? (
                <p className="rounded-xl border border-border bg-card px-5 py-8 text-center text-sm text-muted-foreground">
                  {tab === "matches"
                    ? "No matches waiting. Press “Find new matches” to search."
                    : "Nothing applied yet — apply to a match to see it here."}
                </p>
              ) : (
                <ul className="space-y-3">
                  {visibleApps.map((a) => (
                    <ApplicationRow
                  key={a.id}
                  app={a}
                  busy={busyId === a.id}
                  canApply={sub?.can_apply ?? false}
                  onApply={() => applyNow(a.id)}
                      onStatus={(s) => setStatus(a.id, s)}
                    />
                  ))}
                </ul>
              )}
            </>
          )}
        </div>

        {/* Secondary panel — 1/3 */}
        <div className="space-y-6">
          <ApplyInbox />
          <section className="rounded-xl border border-border bg-card p-6">
            <h2 className="text-sm font-semibold">This period</h2>
            <div className="mt-4 grid grid-cols-2 gap-2">
              <Stat label="Total" value={stats?.total} />
              <Stat label="Submitted" value={stats?.by_status?.submitted ?? 0} />
              <Stat label="Interviews" value={stats?.by_status?.interview ?? 0} />
              <Stat label="Offers" value={stats?.by_status?.offer ?? 0} />
            </div>
          </section>

          {sub && (
            <section className="rounded-xl border border-border bg-card p-6">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold">{sub.plan_name ?? "Free"} plan</h2>
                <Link href="/plans" className="text-xs text-accent">
                  {sub.is_free ? "Upgrade" : "Manage plan"}
                </Link>
              </div>
              <div className="mt-4 space-y-4">
                <Quota
                  label="Applications"
                  used={sub.applications_used}
                  limit={sub.applications_limit}
                />
                <Quota
                  label="Mock interviews"
                  used={sub.interviews_used}
                  limit={sub.interviews_limit}
                />
              </div>
              {!sub.can_apply && (
                <p className="mt-4 rounded-sm bg-warn-bg px-2.5 py-1.5 text-xs text-warn-foreground">
                  Application quota reached for this period.
                </p>
              )}
            </section>
          )}
        </div>
      </div>
    </AppShell>
  );
}

function Stat({ label, value }: { label: string; value?: number | null }) {
  return (
    <div className="rounded-lg border border-border bg-muted p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-[2rem] leading-10 tabular-nums tracking-[-0.02em]">
        {value ?? "—"}
      </p>
    </div>
  );
}

function Quota({
  label,
  used,
  limit,
}: {
  label: string;
  used: number;
  limit: number;
}) {
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="tabular-nums">
          {used}/{limit}
        </span>
      </div>
      <div
        className="mt-1.5 h-1 overflow-hidden rounded-sm bg-border"
        role="progressbar"
        aria-label={`${label} used`}
        aria-valuenow={used}
        aria-valuemin={0}
        aria-valuemax={limit}
      >
        <div
          className={`h-full transition-[width] duration-200 ease-ease ${
            pct >= 100 ? "bg-warn" : "bg-accent"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/**
 * One application.
 *
 * The hard moment is `needs_info`: the user was promised automation and is
 * being asked to finish something. It is designed as *progress that stalled* —
 * the ticks show what Aptil already filled in, then one concrete next step —
 * and it uses the warn colour, never red. Nothing has failed.
 */
/** View / edit / regenerate the cover letter for one application. Editing is
 *  blocked once the application has been submitted (the letter that went out is
 *  a record, not a draft) — the backend enforces this too. */
function CoverLetterSection({ app: a }: { app: Application }) {
  const [letter, setLetter] = useState<string | null>(a.cover_letter);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(a.cover_letter ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const locked = ["submitted", "confirmed", "interview", "offer"].includes(a.status);

  async function regenerate() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.regenerateCoverLetter(a.id);
      setLetter(res.cover_letter);
      setDraft(res.cover_letter ?? "");
      setOpen(true);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't generate it.");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.editCoverLetter(a.id, draft);
      setLetter(res.cover_letter);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save.");
    } finally {
      setBusy(false);
    }
  }

  if (!letter) {
    return (
      <button
        type="button"
        onClick={regenerate}
        disabled={busy}
        className="mt-2 text-xs text-accent underline-offset-4 hover:underline disabled:opacity-50"
      >
        {busy ? "Generating cover letter…" : "Generate a cover letter"}
      </button>
    );
  }

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        {open ? "Hide cover letter" : "View cover letter"}
      </button>
      {open && (
        <div className="mt-2 rounded-lg border border-border bg-card/60 p-3">
          {editing ? (
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={10}
              className="w-full rounded-md border border-border bg-card p-2 text-xs outline-none focus:border-accent"
            />
          ) : (
            <p className="whitespace-pre-wrap text-xs text-muted-foreground">
              {letter}
            </p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
            {locked ? (
              <span className="text-subtle">Already submitted — read only.</span>
            ) : editing ? (
              <>
                <button
                  type="button"
                  onClick={save}
                  disabled={busy}
                  className="text-accent underline-offset-4 hover:underline disabled:opacity-50"
                >
                  Save
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditing(false);
                    setDraft(letter ?? "");
                  }}
                  className="text-muted-foreground underline-offset-4 hover:underline"
                >
                  Cancel
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => setEditing(true)}
                  className="text-accent underline-offset-4 hover:underline"
                >
                  Edit
                </button>
                <button
                  type="button"
                  onClick={regenerate}
                  disabled={busy}
                  className="text-muted-foreground underline-offset-4 hover:underline disabled:opacity-50"
                >
                  {busy ? "Regenerating…" : "Regenerate"}
                </button>
              </>
            )}
            {error && <span className="text-danger">{error}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

function ApplicationRow({
  app: a,
  busy,
  canApply,
  onApply,
  onStatus,
}: {
  app: Application;
  busy: boolean;
  canApply: boolean;
  onApply: () => void;
  onStatus: (status: string) => void;
}) {
  const stalled = a.status === "needs_info";
  // These two are fixed in Settings, not on the employer's site.
  const credentialFix =
    stalled &&
    (a.needs_action === "add_credential" || a.needs_action === "check_credential");
  const filled = a.submitted_fields;
  const doneCount = filled
    ? [filled.name, filled.email, filled.phone, filled.resume].filter(Boolean).length
    : 0;

  return (
    <li
      className={`relative overflow-hidden rounded-xl border border-border p-4 pl-6 ${
        stalled ? "bg-muted" : "bg-card"
      }`}
    >
      <StatusRail status={a.status} />
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-1 gap-4">
          <span
            aria-hidden
            className="grid h-12 w-12 shrink-0 place-items-center rounded-lg border border-border bg-tile text-base text-muted-foreground"
          >
            {(a.job?.company ?? "?").trim().charAt(0).toUpperCase()}
          </span>
          <div className="min-w-0">
            <h3 className="text-sm font-medium">
              {a.job?.title ?? "Role no longer listed"}
            </h3>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {[a.job?.company ?? "—", locationLine(a.job?.location, a.job?.remote)]
                .filter(Boolean)
                .join(" • ")}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StateLabel tone={stalled ? "warn" : a.status === "failed" ? "danger" : "default"}>
                {label(a.status)}
              </StateLabel>
              {stalled && filled?.at && (
                <StalledTicks
                  done={doneCount}
                  total={4}
                  label={`Aptil already filled ${doneCount} of 4 fields`}
                />
              )}
            </div>

            {stalled && (
              <p className="mt-2 max-w-prose text-xs text-warn-foreground">
                {NEEDS_ACTION_COPY[a.needs_action ?? ""] ??
                  a.error_message ??
                  "This one needs you to finish it."}
              </p>
            )}
            {a.error_message && !stalled && (
              <p className="mt-2 text-xs text-muted-foreground">{a.error_message}</p>
            )}

            {a.match_reasons?.length > 0 && (
              <details className="mt-2">
                <summary className="cursor-pointer text-xs text-muted-foreground transition-colors duration-200 ease-ease hover:text-foreground">
                  Why this match?
                </summary>
                <ul className="mt-1.5 space-y-1 pl-4 text-xs text-muted-foreground">
                  {a.match_reasons.map((r, i) => (
                    <li key={i} className="list-disc">
                      {r}
                    </li>
                  ))}
                </ul>
              </details>
            )}

            {a.events && a.events.length > 0 && (
              <details className="mt-2" open={a.status === "queued"}>
                <summary className="cursor-pointer text-xs text-muted-foreground transition-colors duration-200 ease-ease hover:text-foreground">
                  Application activity
                </summary>
                <ol className="mt-1.5 space-y-1 border-l border-border pl-3 text-xs text-muted-foreground">
                  {a.events.map((e, i) => (
                    <li key={i}>
                      <span className="tabular-nums text-subtle">{eventTime(e.at)}</span>
                      {" — "}
                      {eventLabel(e.kind)}
                      {e.detail && e.detail !== e.kind && !(e.kind in EVENT_LABEL) && (
                        <span className="text-subtle"> ({e.detail})</span>
                      )}
                    </li>
                  ))}
                </ol>
              </details>
            )}

            <CoverLetterSection app={a} />
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center justify-end gap-4">
          {stalled ? (
            <span className="inline-flex items-center gap-1.5 rounded-sm bg-warn-bg px-2 py-1 text-xs text-warn-foreground">
              {NEEDS_ACTION_SHORT[a.needs_action ?? ""] ?? "Needs a last step"}
            </span>
          ) : (
            a.match_score != null && (
              <div className="flex flex-col items-end gap-0.5">
                <span className="text-xs text-muted-foreground">Match score</span>
                <ScoreArc value={a.match_score} />
              </div>
            )
          )}

          <div className="flex items-center gap-2">
            {a.status === "matched" && (
              <Button
                size="sm"
                onClick={onApply}
                loading={busy}
                disabled={!canApply}
                title={canApply ? "Submit this application" : "Application quota reached"}
              >
                {!busy && <Send className="h-3 w-3" aria-hidden />}
                Apply
              </Button>
            )}

            {credentialFix ? (
              <Link href="/settings" className={buttonClass("secondary", "sm")}>
                {a.needs_action === "add_credential" ? "Add account" : "Check account"}
              </Link>
            ) : (
              a.job?.apply_url && (
                <a
                  href={a.job.apply_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`Open ${a.job.title} posting in a new tab`}
                  className={buttonClass("secondary", "sm")}
                >
                  {stalled ? (
                    "Resume"
                  ) : (
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                  )}
                </a>
              )
            )}

            {EDITABLE.includes(a.status) && (
              <>
                <label className="sr-only" htmlFor={`status-${a.id}`}>
                  Update status for {a.job?.title ?? "this application"}
                </label>
                <select
                  id={`status-${a.id}`}
                  value={a.status}
                  disabled={busy}
                  onChange={(e) => onStatus(e.target.value)}
                  className="h-8 rounded-sm border border-border bg-card px-2 text-xs"
                >
                  {/* The current value has to be present for the select to
                      show it, but it is not on offer unless the API takes it. */}
                  {!SETTABLE.some(([v]) => v === a.status) && (
                    <option value={a.status} disabled>
                      {STATUS_LABEL[a.status] ?? label(a.status)}
                    </option>
                  )}
                  {SETTABLE.map(([value, text]) => (
                    <option key={value} value={value}>
                      {text}
                    </option>
                  ))}
                </select>
              </>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}
