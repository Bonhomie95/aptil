"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  Check,
  CloudUpload,
  FileText,
  KeyRound,
  Loader2,
  LogOut,
  Plus,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { SiteFooter } from "@/components/site-footer";
import { WorkingLine } from "@/components/signals";
import { CommaListInput } from "@/components/comma-list-input";
import { LocationPicker } from "@/components/location-picker";
import { VoluntaryDisclosures } from "@/components/voluntary-disclosures";
import { Button, ErrorState, FieldError, Notice, Spinner } from "@/components/ui";
import {
  ApiError,
  api,
  type Credential,
  type Demographics,
  type OnboardingState,
  type Profile,
} from "@/lib/api";

/**
 * Steps must mirror the backend `OnboardingStep` enum exactly. When
 * "credentials" was missing here, a user whose saved step was `credentials`
 * landed on a blank card with no way forward.
 *
 * Each carries the heading and the one sentence that step needs — the wizard
 * shows one idea at a time, so the copy is part of the step, not the chrome.
 */

// Values match app/models/profile.py exactly — a mismatch would be silently
// rejected by the API validator rather than showing up in the UI.
const SENIORITY_OPTIONS = [
  ["entry", "Entry level"],
  ["mid", "Mid level"],
  ["senior", "Senior"],
  ["lead", "Lead / Staff / Principal"],
  ["executive", "Director and above"],
] as const;

const STEPS: {
  key: string;
  nav: string;
  title: string;
  blurb: string;
}[] = [
  {
    key: "cv_upload",
    nav: "Résumé",
    title: "Your résumé",
    blurb:
      "Upload a CV and we'll prefill everything below — or build one from scratch. PDF or Word, up to 10 MB.",
  },
  {
    key: "personal_details",
    nav: "Your details",
    title: "Your details",
    blurb:
      "Employers reply to the address you give here, and an application can't be submitted without it.",
  },
  {
    key: "job_history",
    nav: "Experience",
    title: "Experience & skills",
    blurb:
      "Start with your most recent role. Three relevant positions is usually enough to match well; your skills drive the matching directly.",
  },
  {
    key: "job_targets",
    nav: "Targets",
    title: "What are you looking for?",
    blurb:
      "This drives matching more than anything else. Without it we can only guess from your last job title — which is how people end up seeing more of the role they're trying to leave.",
  },
  {
    key: "resume_strategy",
    nav: "Strategy",
    title: "How should we apply?",
    blurb: "You can change this later, per application.",
  },
  {
    key: "voluntary_disclosures",
    nav: "Disclosures",
    title: "Voluntary disclosures",
    blurb:
      "US employers ask these on almost every application. Answering is entirely optional and never affects your matches — we only replay your answers onto forms that ask. Skip the whole step if you'd rather.",
  },
  {
    key: "credentials",
    nav: "Accounts",
    title: "Job site accounts",
    blurb:
      "Optional, and you can skip it. A few employers hide the application form behind a sign-in — this is where you keep those logins.",
  },
  {
    key: "plan_selection",
    nav: "Plan",
    title: "Pick a plan",
    blurb: "You're already on the free plan — this is only if you want more volume.",
  },
];

const MAX_UPLOAD_MB = 10;
const POLL_INTERVAL_MS = 2000;
const POLL_ATTEMPTS = 30;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState("cv_upload");
  const [profile, setProfile] = useState<Profile>({});
  const [hasResume, setHasResume] = useState(false);
  const [mode, setMode] = useState<"upload" | "build" | null>(null);
  const [parseStatus, setParseStatus] = useState<
    "idle" | "parsing" | "done" | "failed" | "timeout"
  >("idle");
  const [parseError, setParseError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [savedOnce, setSavedOnce] = useState(false);
  // Mirrors `dirty.current` for rendering. The ref stays because the
  // beforeunload handler must read the value without re-subscribing.
  const [unsaved, setUnsaved] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const dirty = useRef(false);

  const markDirty = useCallback(() => {
    dirty.current = true;
    setUnsaved(true);
  }, []);

  const applyState = useCallback((s: OnboardingState) => {
    setStep(s.step);
    setProfile((prev) => ({ ...(s.profile ?? {}), ...prev }));
    setHasResume(s.has_resume);
    if (s.has_resume) setMode((m) => m ?? "upload");
    if (s.resume_parse_status === "failed") {
      setParseStatus("failed");
      setParseError(s.resume_parse_error);
    } else if (s.resume_parse_status === "done") {
      setParseStatus("done");
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const s = await api.onboardingState();
      if (s.completed) {
        router.replace("/dashboard");
        return;
      }
      applyState(s);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        router.replace("/login");
        return;
      }
      setLoadError(
        err instanceof Error ? err.message : "Couldn't load your onboarding progress.",
      );
    } finally {
      setLoading(false);
    }
  }, [router, applyState]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const state = await api.onboardingState();
        if (cancelled) return;
        if (state.completed) {
          router.replace("/dashboard");
          return;
        }
        applyState(state);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          router.replace("/login");
          return;
        }
        setLoadError(
          err instanceof Error
            ? err.message
            : "Couldn't load your onboarding progress.",
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router, applyState]);

  useEffect(() => {
    if (step === "credentials") {
      api.listCredentials().then(setCredentials).catch(() => setCredentials([]));
    }
  }, [step]);

  // The header promises "saved as you go" — actually honour it by warning
  // before the tab closes with pending edits.
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirty.current) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, []);

  const stepIndex = STEPS.findIndex((s) => s.key === step);
  // Never render a blank card: an unknown or unrecognised step (e.g. one the
  // backend enum has but the wizard doesn't) falls back to the first screen.
  // Derived rather than written back into state, so there is no extra render.
  const safeIndex = stepIndex === -1 ? 0 : stepIndex;
  const currentStep = STEPS[safeIndex].key;

  function updateProfile(patch: Partial<Profile>) {
    markDirty();
    setProfile((p) => ({ ...p, ...patch }));
  }

  /** Patch one EEO answer without disturbing the others. "" clears it back to
   *  unanswered, which is distinct from an explicit decline. */
  function updateDemographics(patch: Partial<Demographics>) {
    markDirty();
    setProfile((p) => ({
      ...p,
      demographics: { ...(p.demographics ?? {}), ...patch },
    }));
  }

  async function saveProfile(): Promise<boolean> {
    setSaving(true);
    setError(null);
    try {
      await api.updateProfile({
        first_name: profile.first_name ?? undefined,
        last_name: profile.last_name ?? undefined,
        email: profile.email ?? undefined,
        phone: profile.phone ?? undefined,
        city: profile.city ?? undefined,
        country: profile.country ?? undefined,
        headline: profile.headline ?? undefined,
        summary: profile.summary ?? undefined,
        skills: profile.skills ?? undefined,
        work_history: profile.work_history ?? undefined,
        education: profile.education ?? undefined,
        target_titles: profile.target_titles ?? undefined,
        target_seniority: profile.target_seniority ?? undefined,
        target_countries: profile.target_countries ?? undefined,
        demographics: profile.demographics ?? undefined,
      });
      dirty.current = false;
      setUnsaved(false);
      setSavedOnce(true);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save your details.");
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    // Reset immediately so picking the SAME file again still fires onChange.
    if (fileInput.current) fileInput.current.value = "";
    if (!file) return;

    setError(null);
    setParseError(null);

    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setError(
        `That file is ${(file.size / 1024 / 1024).toFixed(1)} MB. The limit is ${MAX_UPLOAD_MB} MB.`,
      );
      return;
    }

    setBusy(true);
    setMode("upload");
    setParseStatus("parsing");
    try {
      // Flush anything typed but not yet saved BEFORE the upload, so the server
      // holds the user's own edits when the parse merges against them. Without
      // this, taking the server's profile below would silently discard them.
      if (dirty.current) await saveProfile();
      const replacing = hasResume;
      await api.uploadResume(file);
      setHasResume(true);
      // Poll until the background parse finishes, then prefill.
      for (let i = 0; i < POLL_ATTEMPTS; i++) {
        await sleep(POLL_INTERVAL_MS);
        const s = await api.onboardingState();
        if (s.resume_parse_status === "done") {
          // Take the server's profile as-is rather than merging into local
          // state. The server has just done the merge that matters (new CV over
          // the old CV's values, never over the user's own edits), so a second
          // "only fill blanks" pass here would re-introduce the exact bug:
          // replace a wrongly-uploaded CV and the stale details stay on screen.
          setProfile(s.profile ?? {});
          dirty.current = false;
          setParseStatus("done");
          setNote(
            replacing
              ? "We re-read your CV and refreshed the details below — anything you had already edited yourself is kept."
              : "We imported what we could — check the next steps and edit anything.",
          );
          return;
        }
        if (s.resume_parse_status === "failed") {
          setParseStatus("failed");
          setParseError(
            s.resume_parse_error ??
              "We couldn't read that file. You can fill your details in manually.",
          );
          return;
        }
      }
      // Be honest that it's still running rather than claiming success.
      setParseStatus("timeout");
    } catch (err) {
      setParseStatus("idle");
      setHasResume(false);
      setError(err instanceof Error ? err.message : "Upload failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function generateResume() {
    setBusy(true);
    setNote(null);
    setError(null);
    try {
      if (!(await saveProfile())) return;
      await api.buildResume();
      setHasResume(true);
      setNote("Your résumé is ready — you can tailor it per job later.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't generate right now.");
    } finally {
      setBusy(false);
    }
  }

  async function advance() {
    setBusy(true);
    setError(null);
    try {
      const next = STEPS[safeIndex + 1]?.key ?? "completed";
      if (
        currentStep === "personal_details" ||
        currentStep === "job_history" ||
        currentStep === "job_targets" ||
        currentStep === "voluntary_disclosures"
      ) {
        if (!(await saveProfile())) return;
      }
      if (currentStep === "resume_strategy") {
        await api.setResumeStrategy(profile.resume_strategy ?? "same");
      }
      await api.setStep(next);
      dirty.current = false;
      setUnsaved(false);
      if (next === "completed") {
        router.push("/dashboard");
        return;
      }
      setStep(next);
      setNote(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function goBack() {
    if (safeIndex === 0) return;
    setBusy(true);
    setError(null);
    try {
      if (dirty.current) await saveProfile();
      const prev = STEPS[safeIndex - 1].key;
      await api.setStep(prev);
      setStep(prev);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't go back.");
    } finally {
      setBusy(false);
    }
  }

  const canContinue =
    (currentStep !== "cv_upload" || hasResume || mode === "build") &&
    (currentStep !== "resume_strategy" || mode !== "build" || hasResume);

  const wh = profile.work_history ?? [];
  const edu = profile.education ?? [];
  const setExp = (i: number, k: string, v: string) => {
    markDirty();
    setProfile((p) => {
      const list = [...(p.work_history ?? [])];
      list[i] = { ...list[i], [k]: v };
      return { ...p, work_history: list };
    });
  };
  const setEdu = (i: number, k: string, v: string) => {
    markDirty();
    setProfile((p) => {
      const list = [...(p.education ?? [])];
      list[i] = { ...list[i], [k]: v };
      return { ...p, education: list };
    });
  };

  const current = STEPS[safeIndex];

  // Steps the user can legitimately leave blank. Saying "Continue" on these
  // while the blurb says "skip this" sends people hunting for a skip control
  // that was never there.
  const OPTIONAL_STEPS = ["voluntary_disclosures", "credentials", "job_targets"];
  const isSkippable = OPTIONAL_STEPS.includes(currentStep);
  const isStepEmpty =
    currentStep === "voluntary_disclosures"
      ? !Object.values(profile.demographics ?? {}).some((v) =>
          Array.isArray(v) ? v.length > 0 : Boolean(v),
        )
      : currentStep === "job_targets"
        ? (profile.target_titles ?? []).length === 0 &&
          !profile.target_seniority &&
          (profile.target_countries ?? []).length === 0
        : currentStep === "credentials"
          ? credentials.length === 0
          : false;
  // Step 4 has two faces: pick a strategy, or generate the résumé you asked us
  // to build. They are different tasks, so they get different headings.
  const buildingResume =
    currentStep === "resume_strategy" && mode === "build" && !hasResume;
  const heading = buildingResume ? "Generate your résumé" : current.title;
  const blurb = buildingResume
    ? "We'll turn the details you entered into a clean résumé you can use to apply."
    : current.blurb;

  return (
    <>
      <WorkingLine active={parseStatus === "parsing"} label="Reading your CV" />
      {/* The top bar is suppressed to a single line: this is a linear flow and
          nothing else on it should look clickable. */}
      <header className="sticky top-0 z-30 border-b border-border bg-card/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-[1200px] items-center gap-3 px-4 lg:px-8">
          <Link href="/" className="text-xl tracking-[-0.01em] text-accent">
            Aptil
          </Link>
          <span className="border-l border-border pl-3 text-sm text-muted-foreground">
            Onboarding
          </span>
          <div className="ml-auto flex items-center gap-3">
            {/* A truthful save indicator beats a progress bar for "leave and
                come back" — it says what actually happened. */}
            <span className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex">
              {saving ? (
                <>
                  <Spinner className="h-3.5 w-3.5" /> Saving…
                </>
              ) : unsaved ? (
                <>
                  <CloudUpload className="h-3.5 w-3.5" aria-hidden /> Unsaved changes
                </>
              ) : savedOnce ? (
                <>
                  <Check className="h-3.5 w-3.5" aria-hidden /> Saved
                </>
              ) : (
                <>
                  <CloudUpload className="h-3.5 w-3.5" aria-hidden /> Saved as you go
                </>
              )}
            </span>
            <ThemeToggle />
            <button
              onClick={async () => {
                await api.logout();
                router.push("/login");
              }}
              className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-muted-foreground transition-colors duration-200 ease-ease hover:bg-muted hover:text-foreground"
            >
              <LogOut className="h-4 w-4" aria-hidden />
              <span className="hidden sm:inline">Sign out</span>
            </button>
          </div>
        </div>
      </header>

      <main id="main" className="min-h-[calc(100vh-4rem)] px-4 py-14 lg:px-8">
        <div className="mx-auto max-w-3xl">
          {/* Progress */}
          <div
            role="progressbar"
            aria-valuenow={safeIndex + 1}
            aria-valuemin={1}
            aria-valuemax={STEPS.length}
            aria-label={`Step ${safeIndex + 1} of ${STEPS.length}: ${current.nav}`}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h1 className="text-sm font-medium">Set up your profile</h1>
              <span className="text-xs tabular-nums text-muted-foreground">
                Step {safeIndex + 1} of {STEPS.length} · {current.nav}
              </span>
            </div>
            <div className="mt-3 flex gap-1">
              {STEPS.map((s, i) => (
                <span
                  key={s.key}
                  aria-hidden
                  className={`h-1 flex-1 rounded-sm transition-colors duration-200 ease-ease ${
                    i <= safeIndex ? "bg-accent" : "bg-border"
                  }`}
                />
              ))}
            </div>
          </div>

          <div className="mt-14">
            <h2 className="font-display text-[2.25rem] leading-[1.15] tracking-[-0.01em] sm:text-[2.75rem]">
              {heading}
            </h2>
            <p className="mt-2 max-w-xl text-base text-muted-foreground sm:text-lg sm:leading-7">
              {blurb}
            </p>
          </div>

          {loading ? (
            <div className="mt-12 flex items-center gap-3 text-sm text-muted-foreground">
              <Spinner /> Loading your progress…
            </div>
          ) : loadError ? (
            <ErrorState message={loadError} onRetry={load} className="mt-12" />
          ) : (
            <div className="mt-12">
              {currentStep === "cv_upload" && (
                <div>
                  <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-card py-12 text-center transition-colors duration-200 ease-ease hover:border-accent">
                    {parseStatus === "parsing" ? (
                      <>
                        <Loader2
                          className="h-6 w-6 animate-spin text-subtle"
                          aria-hidden
                        />
                        <span className="text-sm">Reading your CV…</span>
                        <span className="text-xs text-muted-foreground">
                          This usually takes a few seconds.
                        </span>
                      </>
                    ) : hasResume && mode === "upload" ? (
                      <>
                        <Check className="h-6 w-6 text-positive" aria-hidden />
                        <span className="max-w-md px-4 text-sm">
                          {parseStatus === "done"
                            ? "CV uploaded — details imported into the next steps"
                            : parseStatus === "failed"
                              ? (parseError ??
                                "Uploaded, but we couldn't read it — fill your details in manually")
                              : parseStatus === "timeout"
                                ? "Uploaded. Still reading it — carry on and we'll fill in what we find."
                                : "CV uploaded"}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          Click to replace
                        </span>
                      </>
                    ) : (
                      <>
                        <UploadCloud className="h-6 w-6 text-subtle" aria-hidden />
                        <span className="text-sm">
                          Click to upload your CV (PDF or Word)
                        </span>
                      </>
                    )}
                    <input
                      ref={fileInput}
                      type="file"
                      accept=".pdf,.doc,.docx,application/pdf"
                      onChange={onUpload}
                      disabled={busy}
                      className="sr-only"
                    />
                  </label>

                  <div className="my-6 flex items-center gap-3 text-xs text-subtle">
                    <span className="h-px flex-1 bg-border" /> or{" "}
                    <span className="h-px flex-1 bg-border" />
                  </div>

                  <button
                    onClick={() => {
                      setMode("build");
                      setNote(
                        "Great — fill in your details next and we'll generate a résumé for you.",
                      );
                    }}
                    aria-pressed={mode === "build"}
                    className={`flex w-full items-center justify-center gap-2 rounded-lg border px-4 py-3 text-sm font-medium transition-colors duration-200 ease-ease ${
                      mode === "build"
                        ? "border-accent bg-accent-soft text-accent"
                        : "border-border bg-card hover:border-foreground/40"
                    }`}
                  >
                    <FileText className="h-4 w-4" aria-hidden />
                    I don&apos;t have a résumé — build one for me
                  </button>
                </div>
              )}

              {currentStep === "personal_details" && (
                <div className="space-y-5">
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Input
                      label="First name"
                      autoComplete="given-name"
                      value={profile.first_name}
                      onChange={(v) => updateProfile({ first_name: v })}
                    />
                    <Input
                      label="Last name"
                      autoComplete="family-name"
                      value={profile.last_name}
                      onChange={(v) => updateProfile({ last_name: v })}
                    />
                  </div>
                  <Input
                    label="Contact email"
                    type="email"
                    autoComplete="email"
                    value={profile.email}
                    onChange={(v) => updateProfile({ email: v })}
                    hint="Employers reply here. Applications can't be submitted without it."
                  />
                  <Input
                    label="Phone"
                    type="tel"
                    autoComplete="tel"
                    value={profile.phone}
                    onChange={(v) => updateProfile({ phone: v })}
                  />
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Input
                      label="City"
                      autoComplete="address-level2"
                      value={profile.city}
                      onChange={(v) => updateProfile({ city: v })}
                    />
                    <Input
                      label="Country"
                      autoComplete="country-name"
                      value={profile.country}
                      onChange={(v) => updateProfile({ country: v })}
                    />
                  </div>
                  <Input
                    label="Headline"
                    value={profile.headline}
                    onChange={(v) => updateProfile({ headline: v })}
                    hint="e.g. Senior Backend Engineer"
                  />
                </div>
              )}

              {currentStep === "job_history" && (
                <div className="space-y-8">
                  <CommaListInput
                    label="Skills"
                    value={profile.skills ?? []}
                    onChange={(skills) => updateProfile({ skills })}
                    max={200}
                    hint="Comma separated — these drive job matching."
                  />

                  <Textarea
                    label="Professional summary"
                    value={profile.summary}
                    onChange={(v) => updateProfile({ summary: v })}
                  />

                  <fieldset>
                    <legend className="text-sm font-medium">Work history</legend>
                    <div className="mt-3 space-y-4">
                      {wh.map((w, i) => (
                        <div
                          key={i}
                          className="rounded-lg border border-border bg-card p-5"
                        >
                          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                            <Input
                              label={`Job title (role ${i + 1})`}
                              placeholder="Job title"
                              value={w.title}
                              onChange={(v) => setExp(i, "title", v)}
                            />
                            <Input
                              label={`Company (role ${i + 1})`}
                              placeholder="Company"
                              value={w.company}
                              onChange={(v) => setExp(i, "company", v)}
                            />
                            <Input
                              label={`Start date (role ${i + 1})`}
                              placeholder="e.g. March 2021"
                              value={w.start}
                              onChange={(v) => setExp(i, "start", v)}
                            />
                            <Input
                              label={`End date (role ${i + 1})`}
                              placeholder="or Present"
                              value={w.end}
                              onChange={(v) => setExp(i, "end", v)}
                            />
                          </div>
                          <div className="mt-4">
                            <Textarea
                              label={`What you did (role ${i + 1})`}
                              rows={2}
                              value={w.description}
                              onChange={(v) => setExp(i, "description", v)}
                            />
                          </div>
                          <RemoveBtn
                            label={`Remove role ${i + 1}`}
                            onClick={() =>
                              updateProfile({
                                work_history: wh.filter((_, j) => j !== i),
                              })
                            }
                          />
                        </div>
                      ))}
                      <AddBtn
                        label="Add role"
                        onClick={() => updateProfile({ work_history: [...wh, {}] })}
                      />
                    </div>
                  </fieldset>

                  <fieldset>
                    <legend className="text-sm font-medium">
                      Education{" "}
                      <span className="font-normal text-muted-foreground">
                        (optional)
                      </span>
                    </legend>
                    <div className="mt-3 space-y-4">
                      {edu.map((ed, i) => (
                        <div
                          key={i}
                          className="rounded-lg border border-border bg-card p-5"
                        >
                          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                            <Input
                              label={`Degree (${i + 1})`}
                              value={ed.degree}
                              onChange={(v) => setEdu(i, "degree", v)}
                            />
                            <Input
                              label={`Institution (${i + 1})`}
                              value={ed.institution}
                              onChange={(v) => setEdu(i, "institution", v)}
                            />
                            <Input
                              label={`Year (${i + 1})`}
                              value={ed.year}
                              onChange={(v) => setEdu(i, "year", v)}
                            />
                          </div>
                          <RemoveBtn
                            label={`Remove education ${i + 1}`}
                            onClick={() =>
                              updateProfile({
                                education: edu.filter((_, j) => j !== i),
                              })
                            }
                          />
                        </div>
                      ))}
                      <AddBtn
                        label="Add education"
                        onClick={() => updateProfile({ education: [...edu, {}] })}
                      />
                    </div>
                  </fieldset>
                </div>
              )}

              {currentStep === "job_targets" && (
                <div className="space-y-5">
                  <CommaListInput
                    label="Roles you want"
                    value={profile.target_titles ?? []}
                    onChange={(target_titles) => updateProfile({ target_titles })}
                    max={8}
                    placeholder="Site Reliability Engineer, Platform Engineer"
                    hint="Separate with commas, up to 8. These are matched independently, so listing two very different roles won't make either match worse."
                  />
                  <Select
                    label="Level you're targeting"
                    value={profile.target_seniority}
                    onChange={(v) => updateProfile({ target_seniority: v || null })}
                    options={SENIORITY_OPTIONS}
                    placeholder="No preference"
                  />
                  <div>
                    <p className="mb-2 block text-sm font-medium">
                      Where do you want to work?
                    </p>
                    <LocationPicker
                      value={profile.target_countries ?? []}
                      onChange={(next) =>
                        updateProfile({ target_countries: next })
                      }
                    />
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Your skills and experience still count — this decides which
                    direction, and where, we point them.
                  </p>
                </div>
              )}

              {currentStep === "resume_strategy" && (
                <div>
                  {buildingResume ? (
                    <div className="flex flex-col items-center rounded-xl border border-border bg-card p-10 text-center">
                      <FileText className="h-6 w-6 text-subtle" aria-hidden />
                      <Button
                        onClick={generateResume}
                        loading={busy}
                        size="lg"
                        className="mt-6"
                      >
                        Generate my résumé
                      </Button>
                    </div>
                  ) : (
                    <div
                      className="space-y-3"
                      role="radiogroup"
                      aria-label="Résumé strategy"
                    >
                      {[
                        ["tailored", "Tailor my résumé to each job (recommended)"],
                        ["same", "Use my résumé as-is"],
                        ["none", "Apply without a résumé where allowed"],
                      ].map(([val, label]) => {
                        const active = (profile.resume_strategy ?? "same") === val;
                        return (
                          <button
                            key={val}
                            role="radio"
                            aria-checked={active}
                            onClick={() => updateProfile({ resume_strategy: val })}
                            className={`flex w-full items-center gap-3 rounded-lg border px-4 py-3.5 text-left text-sm transition-colors duration-200 ease-ease ${
                              active
                                ? "border-accent bg-accent-soft"
                                : "border-border bg-card hover:border-foreground/40"
                            }`}
                          >
                            <span
                              aria-hidden
                              className={`grid h-5 w-5 shrink-0 place-items-center rounded-full border ${
                                active
                                  ? "border-accent bg-accent text-accent-foreground"
                                  : "border-border"
                              }`}
                            >
                              {active && <Check className="h-3 w-3" />}
                            </span>
                            {label}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {currentStep === "voluntary_disclosures" && (
                <div className="space-y-6">
                  <div className="rounded-lg border border-border bg-muted/40 p-4 text-sm text-muted-foreground">
                    <p>
                      Every question here is optional and you can change or clear
                      your answers at any time in Settings. They are{" "}
                      <strong className="text-foreground">
                        never used to match, rank or score you
                      </strong>{" "}
                      — we only fill them into an employer&rsquo;s own
                      equal-opportunity questions when a form asks.
                    </p>
                  </div>
                  <VoluntaryDisclosures
                    value={profile.demographics}
                    onChange={updateDemographics}
                  />
                </div>
              )}

              {currentStep === "credentials" && (
                <CredentialsStep credentials={credentials} onChange={setCredentials} />
              )}

              {currentStep === "plan_selection" && (
                <div className="rounded-xl border border-border bg-card p-6">
                  <p className="text-sm text-muted-foreground">
                    The free plan covers a few applications and a mock interview each
                    month. Upgrade whenever you want more — nothing here is required to
                    finish setting up.
                  </p>
                  <Button
                    variant="secondary"
                    onClick={() => router.push("/plans")}
                    className="mt-4"
                  >
                    Compare plans
                  </Button>
                </div>
              )}

              {note && <Notice className="mt-6">{note}</Notice>}
              <FieldError>{error}</FieldError>

              <div className="mt-10 flex items-center justify-between gap-3 border-t border-border pt-6">
                {safeIndex > 0 ? (
                  <Button variant="secondary" onClick={goBack} disabled={busy}>
                    Back
                  </Button>
                ) : (
                  <span />
                )}
                <Button
                  onClick={advance}
                  loading={busy || saving}
                  disabled={!canContinue}
                >
                  {safeIndex >= STEPS.length - 1
                    ? "Finish & go to dashboard"
                    : isSkippable && isStepEmpty
                      ? `Skip for now`
                      : `Continue to step ${safeIndex + 2}`}
                </Button>
              </div>
              {!canContinue && currentStep === "cv_upload" && (
                <p className="mt-3 text-right text-xs text-muted-foreground">
                  Upload a CV or choose &ldquo;build one for me&rdquo; to continue.
                </p>
              )}
            </div>
          )}
        </div>
      </main>

      <SiteFooter />
    </>
  );
}

function CredentialsStep({
  credentials,
  onChange,
}: {
  credentials: Credential[];
  onChange: (c: Credential[]) => void;
}) {
  const [domain, setDomain] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function add() {
    setErr(null);
    setBusy(true);
    try {
      const created = await api.addCredential({
        site_domain: domain,
        login_email: email,
      });
      onChange([...credentials.filter((c) => c.id !== created.id), created]);
      setDomain("");
      setEmail("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't save that credential.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    try {
      await api.deleteCredential(id);
      onChange(credentials.filter((c) => c.id !== id));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't remove that credential.");
    }
  }

  return (
    <div>
      <div className="space-y-3 text-sm text-muted-foreground">
        <p>
          Most sites we apply through — Greenhouse, Lever, Ashby — take applications
          without an account, so you probably need nothing here.{" "}
          <b className="font-medium text-foreground">
            Aptil never creates accounts on your behalf.
          </b>{" "}
          Where a site does insist on one, you register there yourself and save it
          here; we sign in with it when we apply, and park the application if we
          can&apos;t.
        </p>
        <p>
          Leave the password blank and we&apos;ll generate a{" "}
          <b className="font-medium text-foreground">
            unique strong one for that site
          </b>
          , encrypted at rest and never reused anywhere else. You can read it back
          from Settings whenever you need it.
        </p>
      </div>

      <div className="mt-6 space-y-2">
        {credentials.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
            No site accounts yet — you can skip this and add them later.
          </p>
        ) : (
          credentials.map((c) => (
            <div
              key={c.id}
              className="flex items-center justify-between gap-3 rounded-lg border border-border bg-card px-3 py-2.5"
            >
              <div className="flex min-w-0 items-center gap-3">
                <span
                  aria-hidden
                  className="grid h-10 w-10 shrink-0 place-items-center rounded-sm border border-border bg-tile text-muted-foreground"
                >
                  <KeyRound className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{c.site_domain}</p>
                  <p className="truncate font-mono text-xs text-muted-foreground">
                    {c.login_email}
                  </p>
                </div>
              </div>
              <button
                onClick={() => remove(c.id)}
                aria-label={`Remove ${c.site_domain}`}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-sm text-muted-foreground transition-colors duration-200 ease-ease hover:text-danger"
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </button>
            </div>
          ))
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (domain.trim() && email.trim()) add();
        }}
        className="mt-6"
      >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Input
          label="Site domain"
          placeholder="boards.greenhouse.io"
          value={domain}
          onChange={setDomain}
        />
        <Input
          label="Login email for that site"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          value={email}
          onChange={setEmail}
        />
      </div>
      <FieldError>{err}</FieldError>
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
    </div>
  );
}

function Input({
  label,
  value,
  onChange,
  hint,
  type = "text",
  placeholder,
  autoComplete,
}: {
  label: string;
  value?: string | null;
  onChange: (v: string) => void;
  hint?: string;
  type?: string;
  placeholder?: string;
  /** Let the browser fill it. Onboarding asks for exactly the fields every
   *  autofill profile already holds, so not saying so is a wasted minute. */
  autoComplete?: string;
}) {
  // Stable across renders and identical on server and client. The module
  // counter this replaced also renumbered every field below a work-history row
  // whenever one was added or removed.
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value ?? ""}
        placeholder={placeholder}
        autoComplete={autoComplete}
        aria-describedby={hint ? `${id}-hint` : undefined}
        onChange={(e) => onChange(e.target.value)}
        className="h-11 w-full rounded-lg border border-border bg-card px-4 outline-none transition-colors duration-200 ease-ease placeholder:text-subtle focus:border-accent"
      />
      {hint && (
        <p id={`${id}-hint`} className="mt-1.5 text-xs text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
  placeholder,
  hint,
}: {
  label: string;
  value?: string | null;
  onChange: (v: string) => void;
  /** [value, human label] — value must match the API's enum exactly. */
  options: readonly (readonly [string, string])[];
  placeholder?: string;
  hint?: string;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium">
        {label}
      </label>
      <select
        id={id}
        value={value ?? ""}
        aria-describedby={hint ? `${id}-hint` : undefined}
        onChange={(e) => onChange(e.target.value)}
        className="h-11 w-full rounded-lg border border-border bg-card px-4 outline-none transition-colors duration-200 ease-ease focus:border-accent"
      >
        <option value="">{placeholder ?? "Select…"}</option>
        {options.map(([v, labelText]) => (
          <option key={v} value={v}>
            {labelText}
          </option>
        ))}
      </select>
      {hint && (
        <p id={`${id}-hint`} className="mt-1.5 text-xs text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  );
}

function Textarea({
  label,
  value,
  onChange,
  rows = 3,
}: {
  label: string;
  value?: string | null;
  onChange: (v: string) => void;
  rows?: number;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium">
        {label}
      </label>
      <textarea
        id={id}
        rows={rows}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="w-full resize-y rounded-lg border border-border bg-card px-4 py-3 outline-none transition-colors duration-200 ease-ease placeholder:text-subtle focus:border-accent"
      />
    </div>
  );
}

/**
 * "Add another" as a dashed full-width target rather than a small text link:
 * step 3 is where naive designs break, and the fifth row has to be as easy to
 * add as the first.
 */
function AddBtn({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-border py-4 text-sm text-accent transition-colors duration-200 ease-ease hover:border-accent"
    >
      <Plus className="h-3.5 w-3.5" aria-hidden /> {label}
    </button>
  );
}

function RemoveBtn({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="mt-4 flex items-center gap-1 text-xs text-muted-foreground transition-colors duration-200 ease-ease hover:text-danger"
    >
      <Trash2 className="h-3.5 w-3.5" aria-hidden /> Remove
    </button>
  );
}
