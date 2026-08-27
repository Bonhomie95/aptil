"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  AudioLines,
  Mic,
  Square,
  Trash2,
  Volume2,
  VolumeX,
} from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { ScoreArc } from "@/components/signals";
import {
  Button,
  EmptyState,
  ErrorState,
  Notice,
  Skeleton,
  buttonClass,
} from "@/components/ui";
import { useSession } from "@/hooks/use-session";
import { useSpeech } from "@/hooks/use-voice";
import {
  ApiError,
  api,
  type Application,
  type Feedback,
  type InterviewDetail,
  type InterviewSummary,
} from "@/lib/api";

const STORAGE_KEY = "aptil_active_interview";

export default function InterviewPage() {
  const { user, loading: sessionLoading, error: sessionError, retry } = useSession({
    requireOnboarded: true,
  });

  const [session, setSession] = useState<InterviewDetail | null>(null);
  const [history, setHistory] = useState<InterviewSummary[] | null>(null);
  const [idx, setIdx] = useState(0);
  const [answer, setAnswer] = useState("");
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [prepMode, setPrepMode] = useState<"general" | "job" | "paste">("general");
  const [jobId, setJobId] = useState("");
  const [jdText, setJdText] = useState("");
  const [jdTitle, setJdTitle] = useState("");
  const [jdCompany, setJdCompany] = useState("");
  const [apps, setApps] = useState<Application[]>([]);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  // MediaRecorder works on iOS/Safari where SpeechRecognition does not, so it
  // is the cross-device path for spoken answers (audio -> server transcription).
  const canRecord =
    typeof window !== "undefined" &&
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof window.MediaRecorder !== "undefined";
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quotaBlocked, setQuotaBlocked] = useState(false);
  const [voiceMode, setVoiceMode] = useState(false);
  const speech = useSpeech();
  const spokenFor = useRef<string | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await api.listInterviews());
    } catch {
      setHistory([]);
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;

    (async () => {
      // History first, then any session left in progress. Both await before
      // touching state, so no synchronous update happens inside the effect.
      try {
        const list = await api.listInterviews();
        if (!cancelled) setHistory(list);
      } catch {
        if (!cancelled) setHistory([]);
      }

      const savedId = localStorage.getItem(STORAGE_KEY);
      if (!savedId) return;
      try {
        const detail = await api.getInterview(savedId);
        if (cancelled) return;
        if (detail.status === "completed") {
          localStorage.removeItem(STORAGE_KEY);
          return;
        }
        setSession(detail);
        const answered = new Set(detail.transcript.map((t) => t.question_index));
        let next = 0;
        while (answered.has(next) && next < detail.questions.length) next++;
        setIdx(next);
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [user]);

  // Read each question aloud once, when auto-read is on.
  //
  // Depends on `speak` (a useCallback, stable) rather than the whole `speech`
  // object, which useSpeech rebuilds every render — the effect was re-running
  // on every keystroke in the answer box and only the ref guard stopped it
  // speaking again.
  const { speak } = speech;
  useEffect(() => {
    if (!voiceMode || !session) return;
    const q = session.questions[idx];
    if (!q) return;
    const key = `${session.id}:${idx}`;
    if (spokenFor.current === key) return;
    spokenFor.current = key;
    speak(q.question);
  }, [voiceMode, session, idx, speak]);

  function toggleVoice() {
    const next = !voiceMode;
    setVoiceMode(next);
    if (!next) {
      speech.stopSpeaking();
      speech.stopListening();
    } else {
      // Speak the current question immediately on enabling.
      spokenFor.current = null;
    }
  }

  useEffect(() => {
    (async () => {
      try {
        setApps(await api.applications());
      } catch {
        setApps([]);
      }
    })();
  }, []);

  async function startRecording() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        setTranscribing(true);
        try {
          const { text } = await api.transcribeAudio(blob);
          if (text) setAnswer((prev) => (prev ? prev + " " : "") + text);
          else setError("Couldn't hear that clearly — try again or type.");
        } catch {
          setError("Couldn't transcribe that. Please type your answer.");
        } finally {
          setTranscribing(false);
        }
      };
      mr.start();
      recorderRef.current = mr;
      setRecording(true);
    } catch {
      setError("Microphone access is needed to record your answer.");
    }
  }

  function stopRecording() {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setRecording(false);
  }

  async function start() {
    setError(null);
    setQuotaBlocked(false);
    setStarting(true);
    try {
      const body: Parameters<typeof api.createInterview>[0] = { question_count: 6 };
      if (prepMode === "job" && jobId) body.job_id = jobId;
      if (prepMode === "paste" && jdText.trim()) {
        body.job_description = jdText.trim();
        if (jdTitle.trim()) body.job_title = jdTitle.trim();
        if (jdCompany.trim()) body.job_company = jdCompany.trim();
      }
      const detail = await api.createInterview(body);
      // The backend now guarantees a non-empty question list, but guard anyway
      // rather than rendering a dead-end screen.
      if (!detail.questions?.length) {
        setError("We couldn't generate questions this time. Please try again.");
        return;
      }
      setSession(detail);
      localStorage.setItem(STORAGE_KEY, detail.id);
      setIdx(0);
      setFeedback(null);
      setAnswer("");
      loadHistory();
    } catch (err) {
      if (err instanceof ApiError && err.status === 402) {
        setQuotaBlocked(true);
      } else {
        setError(err instanceof Error ? err.message : "Couldn't start a session.");
      }
    } finally {
      setStarting(false);
    }
  }

  async function submit() {
    const text = (speech.listening ? speech.transcript : answer).trim();
    if (!session || !text) return;
    speech.stopListening();
    speech.stopSpeaking();
    setAnswer(text);
    setLoading(true);
    setError(null);
    try {
      const fb = await api.submitAnswer(session.id, idx, text);
      setFeedback(fb);
      if (voiceMode && speech.supported.speak) {
        const summary = [
          `You scored ${fb.score} out of 10.`,
          fb.strengths?.[0] ? `Strength: ${fb.strengths[0]}` : "",
          fb.improvements?.[0] ? `To improve: ${fb.improvements[0]}` : "",
        ]
          .filter(Boolean)
          .join(" ");
        speech.speak(summary);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't score that answer.");
    } finally {
      setLoading(false);
    }
  }

  async function next() {
    speech.stopSpeaking();
    speech.stopListening();
    speech.resetTranscript();
    setFeedback(null);
    setAnswer("");
    const nextIdx = idx + 1;
    setIdx(nextIdx);
    // Past the last question: close the session server-side so the score and
    // summary are actually persisted.
    if (session && nextIdx >= session.questions.length) {
      setFinishing(true);
      try {
        const done = await api.completeInterview(session.id);
        setSession(done);
        localStorage.removeItem(STORAGE_KEY);
        loadHistory();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Couldn't finish the session.");
      } finally {
        setFinishing(false);
      }
    }
  }

  async function skip() {
    if (!session) return;
    // Skipping is just "next without an answer" — the backend records nothing
    // for this index, which is what an unanswered question is.
    await next();
  }

  async function discard() {
    if (!session) return;
    try {
      await api.deleteInterview(session.id);
    } catch {
      // Non-fatal: the local session is cleared regardless.
    }
    localStorage.removeItem(STORAGE_KEY);
    setSession(null);
    setIdx(0);
    setAnswer("");
    setFeedback(null);
    loadHistory();
  }

  if (sessionLoading) {
    return (
      <AppShell>
        <Skeleton className="mx-auto h-10 w-64" />
        <Skeleton className="mx-auto mt-8 h-40 max-w-2xl" />
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

  const current = session?.questions[idx];
  // While recording, the live transcript is the answer; otherwise it's the box.
  const currentAnswer = speech.listening ? speech.transcript : answer;
  const finished =
    session != null &&
    (session.status === "completed" || idx >= session.questions.length);
  const voiceAvailable =
    speech.supported.speak || speech.supported.listen || canRecord;

  return (
    <AppShell
      email={user?.email}
      working={loading}
      workingLabel="Scoring your answer"
    >
      <div className="mx-auto max-w-2xl">
        {/* One question on screen and nothing competing with it: this page is
            used while someone is nervous. */}
        <div className="text-center">
          <h1 className="text-2xl tracking-[-0.02em] sm:text-[32px] sm:leading-10">
            Mock interview
          </h1>
          <p className="mx-auto mt-1 max-w-lg text-sm text-muted-foreground">
            Questions are generated from your CV and target role. Answer, then get
            instant scored feedback.
          </p>
        </div>

        {error && (
          <p role="alert" className="mt-6 text-center text-sm text-danger">
            {error}
          </p>
        )}

        {quotaBlocked && (
          <div className="mt-8 rounded-xl border border-warn/40 bg-warn-bg/40 p-5 text-center">
            <p className="text-sm font-medium text-warn-foreground">
              You&apos;ve used all your mock interviews
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              Your allowance resets at the start of the next billing period, or you
              can upgrade for more.
            </p>
            <Link href="/plans" className={buttonClass("primary", "md", "mt-5")}>
              See plans
            </Link>
          </div>
        )}

        {!session && !quotaBlocked && (
          <div className="mx-auto mt-10 max-w-xl space-y-5">
            <div>
              <p className="mb-2 text-sm font-medium">What are you preparing for?</p>
              <div className="flex flex-wrap gap-2">
                {[
                  ["general", "General practice"],
                  ["job", "A matched job"],
                  ["paste", "Paste a job description"],
                ].map(([key, lbl]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setPrepMode(key as typeof prepMode)}
                    aria-pressed={prepMode === key}
                    className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${
                      prepMode === key
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-border text-muted-foreground hover:border-accent/40"
                    }`}
                  >
                    {lbl}
                  </button>
                ))}
              </div>
            </div>

            {prepMode === "job" && (
              <div>
                <label htmlFor="iv-job" className="mb-1.5 block text-sm font-medium">
                  Which role?
                </label>
                <select
                  id="iv-job"
                  value={jobId}
                  onChange={(e) => setJobId(e.target.value)}
                  className="h-11 w-full rounded-lg border border-border bg-card px-4 outline-none focus:border-accent"
                >
                  <option value="">Choose from your matches…</option>
                  {apps
                    .filter((a) => a.job)
                    .map((a) => (
                      <option key={a.id} value={a.job!.id}>
                        {a.job!.title} — {a.job!.company}
                      </option>
                    ))}
                </select>
                {apps.length === 0 && (
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    No matched jobs yet — paste a description instead.
                  </p>
                )}
              </div>
            )}

            {prepMode === "paste" && (
              <div className="space-y-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <input
                    value={jdTitle}
                    onChange={(e) => setJdTitle(e.target.value)}
                    placeholder="Job title (optional)"
                    className="h-11 rounded-lg border border-border bg-card px-4 text-sm outline-none placeholder:text-subtle focus:border-accent"
                  />
                  <input
                    value={jdCompany}
                    onChange={(e) => setJdCompany(e.target.value)}
                    placeholder="Company (optional)"
                    className="h-11 rounded-lg border border-border bg-card px-4 text-sm outline-none placeholder:text-subtle focus:border-accent"
                  />
                </div>
                <textarea
                  value={jdText}
                  onChange={(e) => setJdText(e.target.value)}
                  rows={8}
                  placeholder="Paste the job description here…"
                  className="w-full rounded-lg border border-border bg-card p-3 text-sm outline-none placeholder:text-subtle focus:border-accent"
                />
              </div>
            )}

            <div className="flex justify-center pt-2">
              <Button
                size="lg"
                onClick={start}
                loading={starting}
                disabled={
                  starting ||
                  (prepMode === "job" && !jobId) ||
                  (prepMode === "paste" && !jdText.trim())
                }
              >
                {starting ? "Preparing questions…" : "Start a practice session"}
              </Button>
            </div>
          </div>
        )}

        {session && !finished && current && (
          <div className="mt-12">
            <p className="text-center text-xs uppercase tracking-[0.1em] text-muted-foreground">
              Question {idx + 1} of {session.questions.length} · {current.type}
            </p>

            <h2 className="mt-6 text-center font-display text-[2rem] leading-[1.2] tracking-[-0.01em] sm:text-[2.75rem] sm:leading-[1.25]">
              {current.question}
            </h2>

            {voiceAvailable && (
              <div className="mt-10 flex justify-center">
                <div className="flex items-center gap-6 rounded-xl border border-border bg-surface p-4">
                  <ClusterButton
                    label={speech.speaking ? "Stop reading" : "Read question aloud"}
                    disabled={!speech.supported.speak}
                    onClick={() =>
                      speech.speaking
                        ? speech.stopSpeaking()
                        : speech.speak(current.question)
                    }
                  >
                    {speech.speaking ? (
                      <VolumeX className="h-[18px] w-[18px]" aria-hidden />
                    ) : (
                      <Volume2 className="h-[18px] w-[18px]" aria-hidden />
                    )}
                  </ClusterButton>

                  <button
                    type="button"
                    aria-label={
                      speech.listening || recording
                        ? "Stop recording"
                        : "Answer by voice"
                    }
                    aria-pressed={speech.listening || recording}
                    disabled={
                      (!speech.supported.listen && !canRecord) ||
                      transcribing ||
                      !!feedback
                    }
                    onClick={() => {
                      if (speech.supported.listen) {
                        // Native, on-device recognition (Chrome/Edge/desktop Safari).
                        if (speech.listening) {
                          speech.stopListening();
                          if (speech.transcript) setAnswer(speech.transcript);
                        } else {
                          setAnswer("");
                          speech.resetTranscript();
                          speech.startListening();
                        }
                      } else if (recording) {
                        stopRecording();
                      } else {
                        startRecording();
                      }
                    }}
                    className={`relative grid h-16 w-16 place-items-center rounded-full border transition-colors duration-200 ease-ease disabled:cursor-not-allowed disabled:opacity-40 ${
                      speech.listening || recording
                        ? "border-accent bg-accent-soft text-accent"
                        : "border-border bg-tile text-foreground hover:border-foreground/40"
                    }`}
                  >
                    {speech.listening || recording ? (
                      <Square className="h-5 w-5" aria-hidden />
                    ) : (
                      <Mic className="h-6 w-6" aria-hidden />
                    )}
                    {(speech.listening || recording) && (
                      <span
                        aria-hidden
                        className="absolute inset-0 rounded-full border border-accent opacity-20"
                      />
                    )}
                  </button>

                  <ClusterButton
                    label={`Read questions aloud automatically: ${voiceMode ? "on" : "off"}`}
                    pressed={voiceMode}
                    disabled={!speech.supported.speak}
                    onClick={toggleVoice}
                  >
                    <AudioLines className="h-5 w-5" aria-hidden />
                  </ClusterButton>
                </div>
              </div>
            )}

            {!speech.supported.listen && !canRecord && voiceAvailable && (
              <p className="mt-3 text-center text-xs text-muted-foreground">
                Voice answers aren&apos;t available on this browser — you can type.
              </p>
            )}
            {transcribing && (
              <p role="status" className="mt-3 text-center text-xs text-accent">
                Transcribing your answer…
              </p>
            )}
            {recording && (
              <p role="status" className="mt-3 text-center text-xs text-accent">
                Recording… tap the mic again when you&apos;re done.
              </p>
            )}
            {speech.error && (
              <p role="alert" className="mt-3 text-center text-xs text-warn">
                {speech.error}
              </p>
            )}
            {speech.listening && (
              <p role="status" className="mt-3 text-center text-xs text-accent">
                Listening…
              </p>
            )}

            <div className="mt-8">
              <label htmlFor="answer" className="sr-only">
                Your answer
              </label>
              <textarea
                id="answer"
                // While the mic is live the transcript IS the answer; copying it
                // into state via an effect would cause a render per word.
                value={currentAnswer}
                onChange={(e) => setAnswer(e.target.value)}
                disabled={!!feedback}
                rows={6}
                maxLength={8000}
                placeholder={
                  speech.listening ? "Listening…" : "Type your answer…"
                }
                className="w-full resize-y rounded-lg border border-border bg-card p-4 text-base leading-7 outline-none transition-colors duration-200 ease-ease placeholder:text-subtle focus:border-accent disabled:opacity-70"
              />
              <div className="mt-1 text-right text-xs tabular-nums text-subtle">
                {currentAnswer.length}/8000
              </div>
            </div>

            <div className="mt-6 flex justify-center gap-4">
              {!feedback ? (
                <>
                  <Button
                    variant="secondary"
                    size="lg"
                    onClick={skip}
                    disabled={loading || finishing}
                    className="min-w-[9rem]"
                  >
                    Skip
                  </Button>
                  <Button
                    size="lg"
                    onClick={submit}
                    loading={loading}
                    disabled={!currentAnswer.trim()}
                    className="min-w-[9rem]"
                  >
                    {loading ? "Scoring…" : "Submit answer"}
                  </Button>
                </>
              ) : (
                <Button
                  size="lg"
                  onClick={next}
                  loading={finishing}
                  className="min-w-[12rem]"
                >
                  {idx + 1 < session.questions.length ? "Next question" : "Finish"}
                  <ArrowRight className="h-4 w-4" aria-hidden />
                </Button>
              )}
            </div>

            <AnimatePresence>
              {feedback && (
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.18, ease: [0.32, 0.72, 0, 1] }}
                  className="mt-8 rounded-xl border border-border bg-card p-6"
                >
                  <div className="flex items-center gap-4">
                    <ScoreArc
                      value={feedback.score / 10}
                      size={56}
                      label="Answer score"
                      digits={0}
                      suffix=""
                    />
                    <div>
                      <p className="text-sm font-semibold">Feedback</p>
                      <p className="text-xs text-muted-foreground">
                        {feedback.score.toFixed(1)} out of 10
                      </p>
                    </div>
                  </div>
                  <FeedbackList title="Strengths" items={feedback.strengths} />
                  <FeedbackList title="To improve" items={feedback.improvements} />
                </motion.div>
              )}
            </AnimatePresence>

            <div className="mt-8 flex justify-center">
              <button
                onClick={discard}
                className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors duration-200 ease-ease hover:text-danger"
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
                Discard this session
              </button>
            </div>
          </div>
        )}

        {session && finished && (
          <div className="mt-12 flex flex-col items-center text-center">
            {/* The serif returns here, once, large and unadorned. No confetti. */}
            {session.overall_score != null ? (
              <>
                <p className="font-display text-[3.5rem] leading-none tabular-nums">
                  {session.overall_score.toFixed(1)}
                </p>
                <p className="mt-3 text-xs text-muted-foreground">
                  Session score out of 10
                </p>
              </>
            ) : (
              <p className="text-lg">Session complete</p>
            )}
            <p className="mt-6 max-w-sm text-sm text-muted-foreground">
              Nice work. Run another whenever you want more practice.
            </p>
            <Button
              size="lg"
              className="mt-6"
              onClick={() => {
                setSession(null);
                setIdx(0);
                start();
              }}
            >
              New session
            </Button>
          </div>
        )}

        {/* Past sessions — previously unreachable: nothing listed them. */}
        <section className="mt-16">
          <h2 className="text-sm font-semibold">Past sessions</h2>
          {history === null ? (
            <Skeleton className="mt-3 h-16" />
          ) : history.length === 0 ? (
            <div className="mt-3 rounded-xl border border-border bg-card">
              <EmptyState
                title="No sessions yet"
                body="Completed practice sessions and their scores will appear here."
              />
            </div>
          ) : (
            <ul className="mt-3 space-y-2">
              {history.map((h) => (
                <li
                  key={h.id}
                  className="flex items-center justify-between gap-4 rounded-xl border border-border bg-card px-4 py-3"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm">
                      {h.role_context ?? "General practice"}
                    </p>
                    <p className="mt-0.5 text-xs tabular-nums text-muted-foreground">
                      {new Date(h.created_at).toLocaleDateString()} ·{" "}
                      {h.answered_count}/{h.question_count} answered ·{" "}
                      {h.status.replace("_", " ")}
                    </p>
                  </div>
                  {h.overall_score != null && (
                    <span className="shrink-0 text-lg tabular-nums">
                      {h.overall_score.toFixed(1)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        {!voiceAvailable && session && (
          <Notice className="mt-8">
            This browser has no speech support, so questions are read on screen and
            answers are typed.
          </Notice>
        )}
      </div>
    </AppShell>
  );
}

/** The two 48px satellites either side of the record button. */
function ClusterButton({
  label,
  onClick,
  disabled,
  pressed,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  pressed?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className={`grid h-12 w-12 place-items-center rounded-full transition-colors duration-200 ease-ease disabled:cursor-not-allowed disabled:opacity-40 ${
        pressed
          ? "bg-accent-soft text-accent"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}

function FeedbackList({ title, items }: { title: string; items: string[] }) {
  if (!items?.length) return null;
  return (
    <div className="mt-5">
      <p className="text-xs uppercase tracking-[0.05em] text-muted-foreground">
        {title}
      </p>
      <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </div>
  );
}
