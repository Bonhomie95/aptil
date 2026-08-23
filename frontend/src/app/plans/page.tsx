"use client";

import { useCallback, useEffect, useState } from "react";
import { Check } from "lucide-react";
import { AppShell, PageHeader } from "@/components/app-shell";
import {
  Button,
  EmptyState,
  ErrorState,
  Notice,
  Skeleton,
  StateLabel,
} from "@/components/ui";
import { useSession } from "@/hooks/use-session";
import { formatPrice, plural } from "@/lib/format";
import { api, type Plan, type Subscription } from "@/lib/api";

export default function PlansPage() {
  const { user, loading: sessionLoading, error: sessionError, retry } = useSession();
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [sub, setSub] = useState<Subscription | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, s] = await Promise.all([api.plans(), api.subscription()]);
      setPlans(p);
      setLoadError(null);
      setSub(s);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Couldn't load plans.");
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const [p, s] = await Promise.all([api.plans(), api.subscription()]);
        if (cancelled) return;
        setPlans(p);
        setSub(s);
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : "Couldn't load plans.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  async function choose(plan: Plan) {
    setError(null);
    setBusy(plan.code);
    try {
      const { url } = await api.checkout(plan.code);
      // assign() rather than mutating location.href: same navigation, and it
      // does not look like an assignment to a value outside the component.
      window.location.assign(url);
    } catch (err) {
      // Report what actually failed instead of always blaming Stripe config.
      setError(err instanceof Error ? err.message : "Couldn't start checkout.");
      setBusy(null);
    }
  }

  async function manage() {
    setError(null);
    setBusy("__portal__");
    try {
      const { url } = await api.billingPortal();
      window.location.assign(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't open the billing portal.");
      setBusy(null);
    }
  }

  if (sessionLoading) {
    return (
      <AppShell>
        <Skeleton className="h-10 w-64" />
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-80" />
          ))}
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

  return (
    <AppShell email={user?.email}>
      <PageHeader
        title="Choose your plan"
        description="Priced by how many applications and interviews we run for you. Start free, upgrade whenever."
        actions={
          sub?.manage_url_available ? (
            <Button
              variant="secondary"
              onClick={manage}
              loading={busy === "__portal__"}
            >
              Manage billing
            </Button>
          ) : undefined
        }
      />

      {sub?.plan_name && (
        <p className="mt-4 text-sm text-muted-foreground">
          You&apos;re on the{" "}
          <b className="font-medium text-foreground">{sub.plan_name}</b> plan
          {sub.current_period_end && !sub.is_free && (
            <> · renews {new Date(sub.current_period_end).toLocaleDateString()}</>
          )}
          .
        </p>
      )}

      {error && (
        <Notice tone="warn" className="mt-6">
          {error}
        </Notice>
      )}

      {loadError ? (
        <ErrorState message={loadError} onRetry={load} className="mt-10" />
      ) : plans === null ? (
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-80" />
          ))}
        </div>
      ) : plans.length === 0 ? (
        <div className="mt-10 rounded-xl border border-border bg-card">
          <EmptyState
            title="No plans available"
            body="The plan catalogue hasn't been set up on this server yet. Try again shortly."
          />
        </div>
      ) : (
        <div
          className={`mt-10 grid items-stretch gap-4 sm:grid-cols-2 ${
            plans.length >= 4 ? "lg:grid-cols-4" : "lg:grid-cols-3"
          }`}
        >
          {plans.map((p) => {
            const current = sub?.plan_code === p.code;
            return (
              <div
                key={p.id}
                className={`flex flex-col rounded-xl border bg-card p-6 ${
                  current || p.is_featured ? "border-foreground" : "border-border"
                }`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <h2 className="text-base font-semibold">{p.name}</h2>
                  {current ? (
                    <StateLabel>Current</StateLabel>
                  ) : (
                    p.is_featured && <StateLabel>Popular</StateLabel>
                  )}
                </div>
                <p className="mt-1 min-h-[3.75rem] text-sm text-muted-foreground">
                  {p.description}
                </p>
                <div className="mt-5 flex items-end gap-1">
                  <span className="text-[2rem] leading-none tabular-nums tracking-[-0.02em]">
                    {p.is_free ? "Free" : formatPrice(p.price_cents, p.currency)}
                  </span>
                  {!p.is_free && (
                    <span className="text-sm text-muted-foreground">/mo</span>
                  )}
                </div>
                <ul className="mt-6 flex-1 space-y-2.5 text-sm text-muted-foreground">
                  <Feature>{plural(p.monthly_applications, "application")} / mo</Feature>
                  <Feature>{plural(p.monthly_interviews, "mock interview")} / mo</Feature>
                  <Feature>{p.prep_minutes} min interview prep</Feature>
                </ul>
                <Button
                  variant={
                    p.is_featured && !current && p.purchasable ? "primary" : "secondary"
                  }
                  onClick={() => choose(p)}
                  disabled={current || p.is_free || !p.purchasable}
                  loading={busy === p.code}
                  title={
                    !p.purchasable && !p.is_free
                      ? "This plan isn't available for purchase yet"
                      : undefined
                  }
                  className="mt-7 w-full"
                >
                  {busy === p.code
                    ? "Redirecting…"
                    : current
                      ? "Your plan"
                      : p.is_free
                        ? "Included"
                        : !p.purchasable
                          ? "Coming soon"
                          : `Choose ${p.name}`}
                </Button>
              </div>
            );
          })}
        </div>
      )}
    </AppShell>
  );
}

function Feature({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      <Check className="mt-0.5 h-4 w-4 shrink-0 text-subtle" aria-hidden />
      <span>{children}</span>
    </li>
  );
}
