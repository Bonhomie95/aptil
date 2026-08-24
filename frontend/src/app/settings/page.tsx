"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Copy,
  Download,
  Eye,
  EyeOff,
  FileText,
  KeyRound,
  Lock,
  ClipboardList,
  Plus,
  Send,
  Wand2,
  Target,
  Trash2,
} from "lucide-react";
import { AppShell, PageHeader } from "@/components/app-shell";
import { Field, PasswordStrength } from "@/components/auth-shell";
import {
  Button,
  ErrorState,
  FieldError,
  Notice,
  Panel,
  Skeleton,
  buttonClass,
} from "@/components/ui";
import { useSession } from "@/hooks/use-session";
import { LocationPicker } from "@/components/location-picker";
import { VoluntaryDisclosures } from "@/components/voluntary-disclosures";
import {
  api,
  type Credential,
  type Demographics,
  type Profile,
  type ResumeDoc,
} from "@/lib/api";

/**
 * Account settings.
 *
 * Layout follows the same 8/4 split the rest of the app uses: routine work in
 * the main column, and everything irreversible pushed into its own column
 * behind a hairline, so a destructive control never sits beside a save button.
 */
export default function SettingsPage() {
  const { user, loading, error: sessionError, retry } = useSession();
  const router = useRouter();

  const [credentials, setCredentials] = useState<Credential[] | null>(null);
  const [resumes, setResumes] = useState<ResumeDoc[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [creds, docs] = await Promise.allSettled([
      api.listCredentials(),
      api.listResumes(),
    ]);
    setCredentials(creds.status === "fulfilled" ? creds.value : []);
    setResumes(docs.status === "fulfilled" ? docs.value : []);
  }, []);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      const [creds, docs] = await Promise.allSettled([
        api.listCredentials(),
        api.listResumes(),
      ]);
      if (cancelled) return;
      setCredentials(creds.status === "fulfilled" ? creds.value : []);
      setResumes(docs.status === "fulfilled" ? docs.value : []);
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  if (loading) {
    return (
      <AppShell>
        <Skeleton className="h-10 w-56" />
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
    <AppShell email={user?.email}>
      <PageHeader
        title="Settings"
        description="Manage your credentials, the files we hold, and what happens to them."
      />

      {notice && <Notice className="mt-6">{notice}</Notice>}

      <div className="mt-8 grid gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-6 lg:col-span-2">
          <ChangePasswordCard
            hasPassword={user?.has_password ?? true}
            onDone={setNotice}
          />
          <SearchPreferencesCard onNotice={setNotice} />
          <ApplyModeCard onNotice={setNotice} />
          <DisclosuresCard onNotice={setNotice} />
          <AutoApplyCard onNotice={setNotice} />
          <CredentialsCard
            credentials={credentials}
            reload={load}
            onNotice={setNotice}
          />
          <ResumesCard resumes={resumes} />
        </div>

        <div className="space-y-6">
          <DataCard onNotice={setNotice} />
          <DangerCard email={user?.email ?? ""} onDeleted={() => router.push("/")} />
        </div>
      </div>
    </AppShell>
  );
}

/**
 * Change — or, for a Google-only account, SET — the local password.
 *
 * Such an account has no current password, so asking for one showed a form
 * that could only ever answer "Current password is incorrect". Now the field
 * is simply absent, and the copy says what the form is for.
 */
function ChangePasswordCard({
  hasPassword,
  onDone,
}: {
  hasPassword: boolean;
  onDone: (s: string) => void;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (next.length < 8) return setError("Use at least 8 characters.");
    if (next !== confirm) return setError("Passwords don't match.");
    setBusy(true);
    try {
      await api.changePassword(hasPassword ? current : null, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      onDone(
        hasPassword
          ? "Password changed. Other devices have been signed out."
          : "Password set. You can now sign in with your email as well as Google.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't change your password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title={hasPassword ? "Account password" : "Set a password"}
      description={
        hasPassword
          ? "Changing it signs you out everywhere else."
          : "You signed up with Google. Adding a password lets you sign in without it — and it's what we check before revealing a stored site password."
      }
      icon={<Lock className="h-4 w-4 text-subtle" aria-hidden />}
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        {hasPassword && (
          <Field
            label="Current password"
            type="password"
            value={current}
            onChange={setCurrent}
            required
            autoComplete="current-password"
          />
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Field
              label="New password"
              type="password"
              value={next}
              onChange={setNext}
              required
              minLength={8}
              autoComplete="new-password"
            />
            <PasswordStrength value={next} />
          </div>
          <Field
            label="Confirm new password"
            type="password"
            value={confirm}
            onChange={setConfirm}
            required
            autoComplete="new-password"
          />
        </div>
        <FieldError>{error}</FieldError>
        <Button type="submit" loading={busy}>
          {hasPassword ? "Change password" : "Set password"}
        </Button>
      </form>
    </Panel>
  );
}

function CredentialsCard({
  credentials,
  reload,
  onNotice,
}: {
  credentials: Credential[] | null;
  reload: () => Promise<void>;
  onNotice: (s: string) => void;
}) {
  const [domain, setDomain] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.addCredential({ site_domain: domain, login_email: email });
      setDomain("");
      setEmail("");
      await reload();
      onNotice("Site account saved with a unique generated password.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save that.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(c: Credential) {
    if (!confirm(`Remove the stored account for ${c.site_domain}?`)) return;
    try {
      await api.deleteCredential(c.id);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't remove that.");
    }
  }

  return (
    <Panel
      title="Job site accounts"
      description="For the few employers that hide their form behind a sign-in. You create the account; we store it encrypted, sign in with it when we apply, and never register anywhere on your behalf."
      icon={<KeyRound className="h-4 w-4 text-subtle" aria-hidden />}
    >
      {credentials === null ? (
        <Skeleton className="h-16" />
      ) : credentials.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
          No site accounts stored.
        </p>
      ) : (
        <ul className="space-y-2">
          {credentials.map((c) => (
            <CredentialRow key={c.id} credential={c} onRemove={() => remove(c)} />
          ))}
        </ul>
      )}

      <form onSubmit={add} className="mt-6 border-t border-border pt-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field
            label="Site domain"
            value={domain}
            onChange={setDomain}
            hint="e.g. boards.greenhouse.io"
          />
          <Field label="Login email" type="email" value={email} onChange={setEmail} />
        </div>
        <FieldError>{error}</FieldError>
        <Button
          type="submit"
          variant="secondary"
          loading={busy}
          disabled={!domain.trim() || !email.trim()}
          className="mt-4"
        >
          {!busy && <Plus className="h-4 w-4" aria-hidden />}
          Add site account
        </Button>
      </form>
    </Panel>
  );
}

/**
 * One stored site credential, with a reveal flow.
 *
 * Aptil generates these passwords, so the user has no other copy — they must be
 * readable. Revealing re-checks the account password server-side (a stolen
 * session token alone is not enough) and the plaintext is held only in this
 * component's state, never written anywhere. The whole flow is deliberately
 * slow: collapsed row → challenge → revealed → auto-hidden after a minute.
 */
function CredentialRow({
  credential,
  onRemove,
}: {
  credential: Credential;
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [revealed, setRevealed] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Never leave a plaintext secret on screen indefinitely.
  useEffect(() => {
    if (!revealed) return;
    const id = setTimeout(() => {
      setRevealed(null);
      setOpen(false);
    }, 60_000);
    return () => clearTimeout(id);
  }, [revealed]);

  async function reveal(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await api.revealCredential(credential.id, password);
      setRevealed(res.password);
      setPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't reveal that.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="rounded-lg border border-border bg-surface p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            aria-hidden
            className="grid h-10 w-10 shrink-0 place-items-center rounded-sm border border-border bg-tile text-muted-foreground"
          >
            <KeyRound className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{credential.site_domain}</p>
            <p className="truncate font-mono text-xs text-muted-foreground">
              {credential.login_email}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span aria-hidden className="font-mono text-sm tracking-[0.1em] text-subtle">
            ••••••••
          </span>
          <button
            onClick={() => {
              setOpen((o) => !o);
              setRevealed(null);
              setError(null);
            }}
            aria-expanded={open}
            className={buttonClass("secondary", "sm")}
          >
            {open ? (
              <>
                <EyeOff className="h-3.5 w-3.5" aria-hidden /> Hide
              </>
            ) : (
              <>
                <Eye className="h-3.5 w-3.5" aria-hidden /> Reveal
              </>
            )}
          </button>
          <button
            onClick={onRemove}
            aria-label={`Remove stored account for ${credential.site_domain}`}
            className="grid h-8 w-8 place-items-center rounded-sm text-muted-foreground transition-colors duration-200 ease-ease hover:text-danger"
          >
            <Trash2 className="h-4 w-4" aria-hidden />
          </button>
        </div>
      </div>

      {open && !revealed && (
        <form onSubmit={reveal} className="mt-3 border-t border-border pt-3">
          <label
            htmlFor={`pw-${credential.id}`}
            className="mb-1.5 block text-xs font-medium"
          >
            Confirm your Aptil password to show it
          </label>
          <div className="flex flex-wrap gap-2">
            <input
              id={`pw-${credential.id}`}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="h-10 min-w-0 flex-1 rounded-lg border border-border bg-card px-3 text-sm outline-none transition-colors duration-200 ease-ease focus:border-accent"
            />
            <Button type="submit" size="sm" loading={busy} disabled={!password}>
              Reveal
            </Button>
          </div>
          <FieldError>{error}</FieldError>
        </form>
      )}

      {revealed && (
        <div className="mt-3 border-t border-border pt-3">
          <div className="flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 break-anywhere rounded-lg bg-muted px-3 py-2 font-mono text-sm">
              {revealed}
            </code>
            <button
              onClick={async () => {
                await navigator.clipboard.writeText(revealed);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              }}
              className={buttonClass("secondary", "sm")}
            >
              <Copy className="h-3.5 w-3.5" aria-hidden />
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Hidden again in a minute. We generated this for {credential.site_domain}{" "}
            and never reuse it anywhere else.
          </p>
        </div>
      )}
    </li>
  );
}

function ResumesCard({ resumes }: { resumes: ResumeDoc[] | null }) {
  return (
    <Panel
      title="Your résumés"
      description="Uploaded CVs and any tailored versions."
      icon={<FileText className="h-4 w-4 text-subtle" aria-hidden />}
    >
      {resumes === null ? (
        <Skeleton className="h-16" />
      ) : resumes.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
          No résumés yet.
        </p>
      ) : (
        <ul className="space-y-2">
          {resumes.map((r) => (
            <li
              key={r.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface px-3 py-2.5"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{r.filename}</p>
                <p className="text-xs text-muted-foreground">
                  {r.kind}
                  {r.size_bytes ? ` · ${(r.size_bytes / 1024).toFixed(0)} KB` : ""}
                  {r.parse_status === "failed" ? " · couldn't be read" : ""}
                </p>
              </div>
              {r.download_url && (
                <a
                  href={r.download_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={buttonClass("secondary", "sm")}
                >
                  Download
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

const SENIORITY_OPTIONS: readonly (readonly [string, string])[] = [
  ["entry", "Entry level"],
  ["mid", "Mid level"],
  ["senior", "Senior"],
  ["lead", "Lead / Staff / Principal"],
  ["executive", "Director and above"],
];

/** What the user is looking for. Editable here because a job search changes —
 *  and because until now these could only be set during onboarding, which is
 *  unreachable once finished, so anyone who signed up earlier could never set
 *  them at all. */
function SearchPreferencesCard({ onNotice }: { onNotice: (s: string) => void }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [titles, setTitles] = useState("");
  const [seniority, setSeniority] = useState("");
  const [excluded, setExcluded] = useState("");
  const [countries, setCountries] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const state = await api.onboardingState();
        if (cancelled) return;
        setProfile(state.profile);
        setTitles((state.profile?.target_titles ?? []).join(", "));
        setSeniority(state.profile?.target_seniority ?? "");
        setExcluded((state.profile?.excluded_companies ?? []).join(", "));
        setCountries(state.profile?.target_countries ?? []);
      } catch {
        if (!cancelled) setProfile(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.updateProfile({
        target_titles: titles
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean)
          .slice(0, 8),
        target_seniority: seniority || null,
        excluded_companies: excluded
          .split(",")
          .map((c) => c.trim())
          .filter(Boolean)
          .slice(0, 200),
        target_countries: countries,
      });
      onNotice("Search preferences saved. Your next match run will use them.");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Couldn't save your preferences.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="What you're looking for"
      description="The single biggest influence on which jobs we match you to."
      icon={<Target className="h-4 w-4 text-subtle" aria-hidden />}
    >
      {profile === null ? (
        <Skeleton className="h-24" />
      ) : (
        <div className="space-y-4">
          <div>
            <label
              htmlFor="target-titles"
              className="mb-1.5 block text-sm font-medium"
            >
              Roles you want
            </label>
            <input
              id="target-titles"
              value={titles}
              onChange={(e) => setTitles(e.target.value)}
              placeholder="Site Reliability Engineer, Platform Engineer"
              aria-describedby="target-titles-hint"
              className="h-11 w-full rounded-lg border border-border bg-card px-4 outline-none transition-colors duration-200 ease-ease placeholder:text-subtle focus:border-accent"
            />
            <p id="target-titles-hint" className="mt-1.5 text-xs text-muted-foreground">
              Separate with commas, up to 8. Leave blank and we fall back to
              guessing from your most recent job title.
            </p>
          </div>

          <div>
            <label htmlFor="target-seniority" className="mb-1.5 block text-sm font-medium">
              Level
            </label>
            <select
              id="target-seniority"
              value={seniority}
              onChange={(e) => setSeniority(e.target.value)}
              className="h-11 w-full rounded-lg border border-border bg-card px-4 outline-none transition-colors duration-200 ease-ease focus:border-accent"
            >
              <option value="">No preference</option>
              {SENIORITY_OPTIONS.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </div>

          <div>
            <p className="mb-2 block text-sm font-medium">
              Where do you want to work?
            </p>
            <LocationPicker value={countries} onChange={setCountries} />
          </div>

          <div>
            <label
              htmlFor="excluded-companies"
              className="mb-1.5 block text-sm font-medium"
            >
              Companies to exclude
            </label>
            <input
              id="excluded-companies"
              value={excluded}
              onChange={(e) => setExcluded(e.target.value)}
              placeholder="Current employer, Acme Corp, a competitor"
              aria-describedby="excluded-hint"
              className="h-11 w-full rounded-lg border border-border bg-card px-4 outline-none transition-colors duration-200 ease-ease placeholder:text-subtle focus:border-accent"
            />
            <p id="excluded-hint" className="mt-1.5 text-xs text-muted-foreground">
              Comma-separated. We never match or apply to these — legal suffixes
              like &ldquo;Inc.&rdquo; are matched automatically, so
              &ldquo;Acme&rdquo; also excludes &ldquo;Acme, Inc.&rdquo;
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={save} loading={busy}>
              Save preferences
            </Button>
          </div>
          <FieldError>{error}</FieldError>
        </div>
      )}
    </Panel>
  );
}

/** Voluntary EEO answers, editable after onboarding.
 *
 *  These cannot be edited by sending the user back through the wizard: doing so
 *  sets onboarding_completed = false, which removes them from the automation
 *  sweep and silently halts their job search. */
function DisclosuresCard({ onNotice }: { onNotice: (s: string) => void }) {
  const [demographics, setDemographics] = useState<Demographics | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const state = await api.onboardingState();
        if (cancelled) return;
        setDemographics(state.profile?.demographics ?? {});
      } catch {
        if (!cancelled) setDemographics({});
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.updateProfile({ demographics: demographics ?? {} });
      onNotice("Voluntary disclosures saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save your answers.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="Voluntary disclosures"
      description="Optional equal-opportunity answers, filled in for you when an employer's form asks. Never used to match or rank you."
      icon={<ClipboardList className="h-4 w-4 text-subtle" aria-hidden />}
    >
      {!loaded ? (
        <Skeleton className="h-24" />
      ) : (
        <div className="space-y-4">
          <VoluntaryDisclosures
            value={demographics}
            onChange={(patch) =>
              setDemographics((d) => ({ ...(d ?? {}), ...patch }))
            }
          />
          <Button onClick={save} loading={busy}>
            Save answers
          </Button>
          <FieldError>{error}</FieldError>
        </div>
      )}
    </Panel>
  );
}

/** Consent for creating job-site accounts on the user's behalf.
 *
 *  When on, an ATS that gates its form behind a sign-in gets an account made
 *  with the user's managed alias — no user password involved — and the site's
 *  verification mail is handled automatically. Off means those sites park for
 *  the user to handle themselves. */
function AutoApplyCard({ onNotice }: { onNotice: (s: string) => void }) {
  const { user } = useSession();
  // Local override once the user toggles; until then, reflect the server value
  // carried on the session. Deriving instead of mirroring avoids a setState in
  // an effect (and the stale-copy bugs that come with it).
  const [override, setOverride] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const serverValue =
    user && "auto_create_accounts" in user
      ? Boolean((user as { auto_create_accounts?: boolean }).auto_create_accounts)
      : true;
  const enabled = override ?? serverValue;

  async function toggle() {
    const next = !enabled;
    setBusy(true);
    setOverride(next);
    try {
      await api.setAutoCreate(next);
      onNotice(
        next
          ? "Aptil will create accounts for you on sites that require sign-in."
          : "Aptil will no longer create accounts — those sites will park for you.",
      );
    } catch {
      setOverride(!next);
      onNotice("Couldn't update that setting.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="Create accounts for me"
      description="Some employers hide their form behind a sign-in. When this is on, Aptil creates the account for you using a private Aptil email address — you never share a password — and handles the verification email automatically."
      icon={<Wand2 className="h-4 w-4 text-subtle" aria-hidden />}
    >
      <label className="flex cursor-pointer items-center gap-3">
        <input
          type="checkbox"
          checked={enabled}
          disabled={busy}
          onChange={toggle}
          className="h-4 w-4 rounded border-border accent-accent"
        />
        <span className="text-sm">
          {enabled ? "On — accounts created automatically" : "Off — I'll handle sign-in sites myself"}
        </span>
      </label>
    </Panel>
  );
}

/** Toggle background auto-apply vs review-then-batch. Discovery/matching run
 *  either way — this only decides whether matched jobs are submitted
 *  automatically or wait for the user to press Apply on the dashboard. */
function ApplyModeCard({ onNotice }: { onNotice: (s: string) => void }) {
  const { user } = useSession();
  const [override, setOverride] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const serverValue =
    user && "auto_apply" in user
      ? Boolean((user as { auto_apply?: boolean }).auto_apply)
      : true;
  const enabled = override ?? serverValue;

  async function toggle() {
    const next = !enabled;
    setBusy(true);
    setOverride(next);
    try {
      await api.setAutoApply(next);
      onNotice(
        next
          ? "Auto-apply is on — Aptil submits your matches automatically."
          : "Auto-apply is off — your matches wait on the dashboard until you press Apply.",
      );
    } catch {
      setOverride(!next);
      onNotice("Couldn't update that setting.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="Apply automatically"
      description="On: Aptil applies to your matches in the background. Off: matches are found and shown on your dashboard, and you apply to them in batches yourself (faster searches, more control)."
      icon={<Send className="h-4 w-4 text-subtle" aria-hidden />}
    >
      <label className="flex cursor-pointer items-center gap-3">
        <input
          type="checkbox"
          checked={enabled}
          disabled={busy}
          onChange={toggle}
          className="h-4 w-4 rounded border-border accent-accent"
        />
        <span className="text-sm">
          {enabled
            ? "On — applying automatically in the background"
            : "Off — I'll review and apply from the dashboard"}
        </span>
      </label>
    </Panel>
  );
}

function DataCard({ onNotice }: { onNotice: (s: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function exportData() {
    setBusy(true);
    setError(null);
    try {
      const data = await api.exportData();
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `aptil-export-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      onNotice("Your data export has been downloaded.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't export your data.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="Your data"
      description="Download everything we hold about you as JSON."
      icon={<Download className="h-4 w-4 text-subtle" aria-hidden />}
    >
      <Button variant="secondary" onClick={exportData} loading={busy}>
        Export my data
      </Button>
      <FieldError>{error}</FieldError>
    </Panel>
  );
}

function DangerCard({
  email,
  onDeleted,
}: {
  email: string;
  onDeleted: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmEmail, setConfirmEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.deleteAccount({
        password: password || undefined,
        confirm_email: confirmEmail || undefined,
      });
      await api.logout();
      onDeleted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't delete your account.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      tone="danger"
      title="Danger zone"
      description="Permanently removes your profile, résumés, applications and interview history. This cannot be undone."
      icon={<AlertTriangle className="h-4 w-4" aria-hidden />}
    >
      {!open ? (
        <Button variant="danger" onClick={() => setOpen(true)}>
          Delete my account
        </Button>
      ) : (
        <form onSubmit={remove} className="space-y-4" noValidate>
          <Field
            label="Confirm your password"
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete="current-password"
            hint={`Signed in with Google instead? Type ${email} below.`}
          />
          <Field
            label="Or type your email to confirm"
            value={confirmEmail}
            onChange={setConfirmEmail}
          />
          <FieldError>{error}</FieldError>
          <div className="flex flex-wrap gap-3">
            <Button
              type="submit"
              variant="danger"
              loading={busy}
              disabled={!password && !confirmEmail}
            >
              Permanently delete
            </Button>
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        </form>
      )}
    </Panel>
  );
}
