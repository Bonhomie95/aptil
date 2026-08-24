"use client";

import { useCallback, useEffect, useState } from "react";
import { ExternalLink, Search } from "lucide-react";
import { AppShell, PageHeader } from "@/components/app-shell";
import {
  Button,
  EmptyState,
  ErrorState,
  Skeleton,
  StateLabel,
  buttonClass,
} from "@/components/ui";
import { useSession } from "@/hooks/use-session";
import { formatSalary, locationLine, relativeTime } from "@/lib/format";
import { Pagination } from "@/components/pagination";
import { api, type JobSummary } from "@/lib/api";

const salaryLabel = (job: JobSummary) =>
  formatSalary(job.salary_min, job.salary_max, job.currency);

export default function JobsPage() {
  const { user, loading: sessionLoading, error: sessionError, retry } = useSession({
    requireOnboarded: true,
  });
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [search, setSearch] = useState("");
  // The query behind the results currently shown. Submitting copies `search`
  // into it; the fetch effect reads only this.
  const [applied, setApplied] = useState("");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(0);
  const [perPage, setPerPage] = useState(25);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setJobs(
        await api.availableJobs({
          search: applied || undefined,
          remote: remoteOnly ? true : undefined,
          limit: perPage,
          offset: page * perPage,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load jobs.");
    } finally {
      setBusy(false);
    }
  }, [applied, remoteOnly, page, perPage]);

  // Runs on mount and whenever the remote filter flips. `applied` is the search
  // that produced what is on screen, NOT the text currently in the box: the
  // filter must not run a search the user has typed but not submitted, and it
  // must not drop one they did submit — toggling "Remote only" after searching
  // used to silently clear the query and show everything.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const results = await api.availableJobs({
          search: applied || undefined,
          remote: remoteOnly ? true : undefined,
          limit: perPage,
          offset: page * perPage,
        });
        if (!cancelled) {
          setJobs(results);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Couldn't load jobs.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, remoteOnly, applied, page, perPage]);

  if (sessionLoading) {
    return (
      <AppShell>
        <Skeleton className="h-10 w-52" />
        <Skeleton className="mt-8 h-64" />
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

  return (
    <AppShell email={user?.email} working={busy} workingLabel="Searching roles">
      <PageHeader
        title="Discovered roles"
        description="The shared pool of jobs Aptil has found from official job APIs and company ATS boards."
      />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          setApplied(search.trim());
          setPage(0);
        }}
        className="mt-8 flex flex-wrap items-center gap-3"
      >
        <div className="relative min-w-[16rem] flex-1">
          <label htmlFor="job-search" className="sr-only">
            Search by title or company
          </label>
          <Search
            className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle"
            aria-hidden
          />
          <input
            id="job-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search title or company…"
            className="h-10 w-full rounded-lg border border-border bg-card pl-10 pr-3 text-sm outline-none transition-colors duration-200 ease-ease placeholder:text-subtle focus:border-accent"
          />
        </div>
        <label className="flex h-10 cursor-pointer items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={remoteOnly}
            onChange={(e) => {
              setRemoteOnly(e.target.checked);
              setPage(0);
            }}
            className="h-4 w-4 rounded-sm border-border accent-[var(--color-accent)]"
          />
          Remote only
        </label>
        <Button type="submit" loading={busy}>
          Search
        </Button>
      </form>

      <div className="mt-6">
        {error ? (
          <ErrorState message={error} onRetry={load} />
        ) : jobs === null ? (
          <div className="space-y-3">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
        ) : jobs.length === 0 ? (
          <div className="rounded-xl border border-border bg-card">
            <EmptyState
              title="No roles yet"
              body={
                search || remoteOnly
                  ? "Nothing matched those filters. Try a broader search."
                  : "Discovery runs on a schedule. Once it finds roles they'll show up here and get matched to your profile."
              }
            />
          </div>
        ) : (
          <ul className="space-y-3">
            {jobs.map((j) => (
              <li
                key={j.id}
                className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border bg-card p-4"
              >
                <div className="flex min-w-0 flex-1 gap-4">
                  <span
                    aria-hidden
                    className="grid h-12 w-12 shrink-0 place-items-center rounded-lg border border-border bg-tile text-base text-muted-foreground"
                  >
                    {j.company.trim().charAt(0).toUpperCase()}
                  </span>
                  <div className="min-w-0">
                    <h2 className="text-sm font-medium">{j.title}</h2>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      {[j.company, locationLine(j.location, j.remote)]
                        .filter(Boolean)
                        .join(" • ")}
                    </p>
                    <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs">
                      {salaryLabel(j) && (
                        <span className="tabular-nums text-positive">
                          {salaryLabel(j)}
                        </span>
                      )}
                      {/* How stale a posting is changes whether it is worth
                          applying to, and we already store posted_at. */}
                      {relativeTime(j.posted_at ?? null) && (
                        <span className="text-subtle">
                          Posted {relativeTime(j.posted_at ?? null)}
                        </span>
                      )}
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <StateLabel>{j.source}</StateLabel>
                  <a
                    href={j.apply_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={buttonClass("secondary", "sm")}
                  >
                    View <ExternalLink className="h-3 w-3" aria-hidden />
                  </a>
                </div>
              </li>
            ))}
          </ul>
        )}
        {jobs && jobs.length > 0 && (
          <Pagination
            page={page}
            perPage={perPage}
            count={jobs.length}
            busy={busy}
            onPage={setPage}
            onPerPage={(n) => {
              setPerPage(n);
              setPage(0);
            }}
          />
        )}
      </div>
    </AppShell>
  );
}
