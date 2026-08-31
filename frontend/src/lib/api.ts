// Thin API client for the Aptil backend.
//
// Handles the two things the previous version left out:
//  - Access tokens expire after 30 minutes. A 401 now transparently refreshes
//    once (deduplicated across concurrent callers) and replays the request,
//    instead of silently logging the user out mid-task.
//  - FastAPI validation errors arrive as `detail: [{...}]`. Rendering that
//    object directly produced "[object Object]" in the UI.

// Empty string = same-origin, which is what you get when the Next server proxies
// /api to the backend (see API_PROXY_TARGET in next.config.mjs). That mode needs
// nothing baked into this bundle, so one build works in every environment.
// Falls back to the build-time value, then to the local dev default.
const BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);
const PREFIX = "/api/v1";

const ACCESS_KEY = "aptil_access";
const REFRESH_KEY = "aptil_refresh";

export type Tokens = {
  access_token: string;
  refresh_token: string;
  expires_in?: number;
};

export const googleLoginUrl = `${BASE}${PREFIX}/auth/google/login`;

/** Error carrying the HTTP status so callers can branch on it. */
export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

// --- token storage --------------------------------------------------------
export const tokenStore = {
  access: () =>
    typeof window === "undefined" ? null : localStorage.getItem(ACCESS_KEY),
  refresh: () =>
    typeof window === "undefined" ? null : localStorage.getItem(REFRESH_KEY),
  set(tokens: Tokens) {
    if (typeof window === "undefined") return;
    localStorage.setItem(ACCESS_KEY, tokens.access_token);
    localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  },
  clear() {
    if (typeof window === "undefined") return;
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

/** Turn any backend error body into a single readable sentence. */
function messageFrom(body: unknown, status: number): string {
  if (typeof body === "string" && body.trim()) return body;
  if (body && typeof body === "object") {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    // Defensive: older/other FastAPI handlers still return the raw array.
    if (Array.isArray(detail)) {
      const parts = detail
        .map((d) => {
          if (typeof d === "string") return d;
          const item = d as { loc?: unknown[]; msg?: string; field?: string; message?: string };
          const field =
            item.field ??
            (Array.isArray(item.loc)
              ? item.loc.filter((p) => p !== "body" && p !== "query").join(" → ")
              : "");
          const msg = item.message ?? item.msg ?? "Invalid value";
          return field ? `${field}: ${msg}` : msg;
        })
        .filter(Boolean);
      if (parts.length) return parts.join("; ");
    }
  }
  if (status === 401) return "Your session has expired. Please log in again.";
  if (status === 403) return "You don't have access to that.";
  if (status === 404) return "Not found.";
  if (status === 429) return "Too many attempts. Please wait a moment and try again.";
  if (status >= 500) return "Something went wrong on our side. Please try again.";
  return `Request failed (${status})`;
}

// --- refresh coordination -------------------------------------------------
// One in-flight refresh shared by every concurrent 401, so a page that fires
// several requests at once doesn't burn (and invalidate) the rotating token
// multiple times.
let refreshInFlight: Promise<boolean> | null = null;

/** Called when refreshing fails and the user must log in again. */
let onSessionExpired: (() => void) | null = null;
export function setSessionExpiredHandler(fn: (() => void) | null) {
  onSessionExpired = fn;
}

async function refreshTokens(): Promise<boolean> {
  const refresh_token = tokenStore.refresh();
  if (!refresh_token) return false;

  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(`${BASE}${PREFIX}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token }),
        });
        if (!res.ok) return false;
        const tokens = (await res.json()) as Tokens;
        tokenStore.set(tokens);
        return true;
      } catch {
        return false;
      } finally {
        // Release the lock on the next tick so racing callers see the result.
        setTimeout(() => {
          refreshInFlight = null;
        }, 0);
      }
    })();
  }
  return refreshInFlight;
}

type RequestOptions = RequestInit & { skipAuthRetry?: boolean };

async function rawRequest(
  path: string,
  options: RequestOptions = {},
): Promise<Response> {
  const { skipAuthRetry, ...init } = options;
  const token = tokenStore.access();
  const isFormData = init.body instanceof FormData;

  const headers: Record<string, string> = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...((init.headers as Record<string, string>) || {}),
  };

  let res: Response;
  try {
    res = await fetch(`${BASE}${PREFIX}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(
      "Can't reach the server. Check your connection and try again.",
      0,
    );
  }

  // Transparently refresh once, then replay the original request.
  if (res.status === 401 && !skipAuthRetry && tokenStore.refresh()) {
    const refreshed = await refreshTokens();
    if (refreshed) {
      return rawRequest(path, { ...options, skipAuthRetry: true });
    }
    tokenStore.clear();
    onSessionExpired?.();
  }
  return res;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const res = await rawRequest(path, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const code =
      body && typeof body === "object" && typeof body.detail === "string"
        ? body.detail
        : undefined;
    throw new ApiError(messageFrom(body, res.status), res.status, code);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

// --- types ----------------------------------------------------------------
export type InterviewQuestion = {
  type: string;
  question: string;
  what_good_looks_like?: string;
};

export type Me = {
  id: string;
  email: string;
  full_name: string | null;
  is_email_verified: boolean;
  onboarding_step: string;
  onboarding_completed: boolean;
  /** False for Google-only accounts, which have no local password to confirm. */
  has_password: boolean;
  /** Background auto-apply on, vs review-then-batch-apply. */
  auto_apply?: boolean;
  auto_create_accounts?: boolean;
  two_factor_enabled?: boolean;
};

export type Profile = {
  id?: string;
  first_name?: string | null;
  last_name?: string | null;
  email?: string | null;
  phone?: string | null;
  city?: string | null;
  country?: string | null;
  headline?: string | null;
  summary?: string | null;
  skills?: string[];
  work_history?: Record<string, string>[];
  education?: Record<string, string>[];
  target_titles?: string[];
  target_seniority?: string | null;
  excluded_companies?: string[];
  target_countries?: string[];
  demographics?: Demographics | null;
  resume_strategy?: string | null;
  preferences?: Record<string, unknown>;
};

/** Voluntary EEO self-identification. Every field optional; null = unanswered.
 *  "decline_to_self_identify" is a real answer, not an absence. */
export type Demographics = {
  gender?: string | null;
  hispanic_or_latino?: string | null;
  race?: string | null;
  veteran_status?: string | null;
  /** The four VEVRAA classifications; several can apply at once. */
  veteran_categories?: string[];
  disability_status?: string | null;
};

export type OnboardingState = {
  step: string;
  completed: boolean;
  profile: Profile | null;
  has_resume: boolean;
  resume_parse_status: string | null;
  resume_parse_error: string | null;
  steps: string[];
};

/** Whether the engine may source, match and apply on the user's behalf.
 *  "paused" leaves already-queued applications to go out; "stopped" cancels
 *  them, so nothing is submitted after the user says stop. */
export type AutomationState = "running" | "paused" | "stopped";

export type AutomationStatus = {
  state: AutomationState;
  changed_at: string | null;
  /** Queued but not yet submitted. */
  queued: number;
};

/** One message received on the user's managed apply alias. */
export type InboxItem = {
  id: string;
  from_address: string;
  subject: string;
  body_text: string;
  kind: "verification" | "confirmation" | "interview" | "rejection" | "other";
  sender_domain: string;
  received_at: string | null;
};

export type Plan = {
  id: string;
  code: string;
  name: string;
  description: string | null;
  price_cents: number;
  currency: string;
  is_featured: boolean;
  monthly_applications: number;
  monthly_interviews: number;
  prep_minutes: number;
  features: Record<string, unknown>;
  is_free: boolean;
  purchasable: boolean;
};

export type Subscription = {
  subscription_id: string | null;
  plan_code: string | null;
  plan_name: string | null;
  status: string | null;
  is_free: boolean;
  current_period_end: string | null;
  applications_used: number;
  applications_limit: number;
  interviews_used: number;
  interviews_limit: number;
  can_apply: boolean;
  can_interview: boolean;
  manage_url_available: boolean;
};

export type JobSummary = {
  id: string;
  company: string;
  title: string;
  location: string | null;
  remote: boolean | null;
  source: string;
  apply_url: string;
  salary_min: number | null;
  salary_max: number | null;
  currency: string | null;
  /** When the employer posted it. The API has always returned this. */
  posted_at: string | null;
};

export type Application = {
  id: string;
  status: string;
  match_score: number | null;
  match_reasons: string[];
  cover_letter: string | null;
  error_message: string | null;
  submitted_at: string | null;
  created_at: string;
  job: JobSummary | null;
  /** What the apply engine actually put on the form. */
  submitted_fields?: {
    name?: boolean;
    email?: boolean;
    phone?: boolean;
    resume?: boolean;
    at?: string;
  } | null;
  /** Machine-readable reason this row needs the user, if it does. */
  needs_action?: string | null;
  credential_id?: string | null;
  /** Timestamped audit trail: queued -> apply_started -> outcome. */
  events?: { at: string; kind: string; detail?: string }[];
};

export type InterviewSummary = {
  id: string;
  status: string;
  role_context: string | null;
  question_count: number;
  answered_count: number;
  overall_score: number | null;
  created_at: string;
  completed_at: string | null;
};

export type InterviewDetail = InterviewSummary & {
  questions: InterviewQuestion[];
  transcript: {
    question_index: number;
    question: string;
    answer: string;
    feedback: Feedback;
  }[];
  feedback: Record<string, unknown>;
};

export type Feedback = {
  score: number;
  strengths: string[];
  improvements: string[];
};

export type Credential = {
  id: string;
  site_domain: string;
  login_email: string;
  has_password: boolean;
};

export type ResumeDoc = {
  id: string;
  kind: string;
  filename: string;
  parse_status: string;
  parse_error: string | null;
  size_bytes: number | null;
  download_url: string | null;
};

// --- api ------------------------------------------------------------------
export const api = {
  register: (body: {
    email: string;
    password: string;
    full_name?: string;
    accepted_terms: boolean;
  }) => request<Me>("/auth/register", { method: "POST", body: JSON.stringify(body) }),

  verifyEmail: (token: string) =>
    request<Me>("/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  resendVerification: (email: string) =>
    request<{ sent: boolean; next_cooldown_seconds: number }>(
      "/auth/resend-verification",
      { method: "POST", body: JSON.stringify({ email }) },
    ),

  login: async (body: { email: string; password: string }) => {
    const res = await request<Tokens | { two_factor_required: true; challenge: string }>(
      "/auth/login",
      { method: "POST", body: JSON.stringify(body), skipAuthRetry: true },
    );
    if ("two_factor_required" in res) return res; // caller prompts for the code
    tokenStore.set(res);
    return res;
  },
  verifyTwoFactor: async (challenge: string, code: string) => {
    const tokens = await request<Tokens>("/auth/2fa/verify", {
      method: "POST",
      body: JSON.stringify({ challenge, code }),
      skipAuthRetry: true,
    });
    tokenStore.set(tokens);
    return tokens;
  },
  twoFactorSetup: () =>
    request<{ secret: string; otpauth_uri: string }>("/auth/2fa/setup", {
      method: "POST",
    }),
  twoFactorEnable: (code: string) =>
    request<{ enabled: boolean; backup_codes: string[] }>("/auth/2fa/enable", {
      method: "POST",
      body: JSON.stringify({ code }),
    }),
  twoFactorDisable: (code: string) =>
    request<{ enabled: boolean }>("/auth/2fa/disable", {
      method: "POST",
      body: JSON.stringify({ code }),
    }),

  forgotPassword: (email: string) =>
    request<{ sent: boolean }>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  resetPassword: async (token: string, password: string) => {
    const tokens = await request<Tokens>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, password }),
      skipAuthRetry: true,
    });
    tokenStore.set(tokens);
    return tokens;
  },

  changePassword: async (current_password: string | null, new_password: string) => {
    const tokens = await request<Tokens>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({
        // Omitted entirely for an account that has none, rather than sent empty.
        ...(current_password ? { current_password } : {}),
        new_password,
      }),
    });
    tokenStore.set(tokens);
    return tokens;
  },

  me: () => request<Me>("/auth/me"),

  logout: async (allDevices = false) => {
    const refresh_token = tokenStore.refresh();
    try {
      if (tokenStore.access()) {
        await request<void>("/auth/logout", {
          method: "POST",
          body: JSON.stringify({ refresh_token, all_devices: allDevices }),
          skipAuthRetry: true,
        });
      }
    } catch {
      // Server-side revocation is best-effort; the local session is cleared
      // either way so the user is never stuck "logged in".
    } finally {
      tokenStore.clear();
    }
  },

  // --- onboarding ---
  onboardingState: () => request<OnboardingState>("/onboarding/state"),
  uploadResume: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<OnboardingState>("/onboarding/resume", {
      method: "POST",
      body: form,
    });
  },
  listResumes: () => request<ResumeDoc[]>("/onboarding/resumes"),
  updateProfile: (body: Partial<Profile>) =>
    request<Profile>("/onboarding/profile", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  setStep: (step: string) =>
    request<OnboardingState>("/onboarding/step", {
      method: "POST",
      body: JSON.stringify({ step }),
    }),
  setResumeStrategy: (strategy: string) =>
    request<Profile>("/onboarding/resume-strategy", {
      method: "POST",
      body: JSON.stringify({ strategy }),
    }),
  buildResume: () =>
    request<OnboardingState>("/onboarding/build-resume", { method: "POST" }),

  listCredentials: () => request<Credential[]>("/onboarding/credentials"),
  addCredential: (body: {
    site_domain: string;
    login_email: string;
    password?: string;
  }) =>
    request<Credential>("/onboarding/credentials", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteCredential: (id: string) =>
    request<void>(`/onboarding/credentials/${id}`, { method: "DELETE" }),
  /** Re-authenticates with the account password before returning the secret. */
  revealCredential: (id: string, password: string) =>
    request<{
      id: string;
      site_domain: string;
      login_email: string;
      password: string;
      revealed_at: string;
    }>(`/onboarding/credentials/${id}/reveal`, {
      method: "POST",
      body: JSON.stringify({ password }),
    }),

  // --- plans & billing ---
  plans: () => request<Plan[]>("/plans"),
  checkout: (plan_code: string) =>
    request<{ url: string }>("/billing/checkout", {
      method: "POST",
      body: JSON.stringify({ plan_code }),
    }),
  billingPortal: () =>
    request<{ url: string }>("/billing/portal", { method: "POST" }),
  subscription: () => request<Subscription>("/billing/subscription"),

  // --- jobs ---
  applications: (params?: { status?: string; includeAll?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.includeAll) qs.set("include_all", "true");
    const q = qs.toString();
    return request<Application[]>(`/jobs/applications${q ? `?${q}` : ""}`);
  },
  availableJobs: (params?: {
    search?: string;
    remote?: boolean;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.search) qs.set("search", params.search);
    if (params?.remote !== undefined) qs.set("remote", String(params.remote));
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.offset) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return request<JobSummary[]>(`/jobs/available${q ? `?${q}` : ""}`);
  },
  stats: () =>
    request<{
      by_status: Record<string, number>;
      total: number;
      applications_used: number;
    }>("/jobs/stats"),
  updateApplicationStatus: (id: string, status: string) =>
    request<Application>(`/jobs/applications/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  applyNow: (id: string) =>
    request<{ queued: number; detail: string | null }>(
      `/jobs/applications/${id}/apply`,
      { method: "POST" },
    ),
  requestMatching: () =>
    request<{ queued: number; detail: string | null; task_id: string | null }>(
      "/jobs/match",
      { method: "POST" },
    ),
  matchingStatus: () =>
    request<{ running: boolean; task_id: string | null; started_at: string | null }>(
      "/jobs/match/status",
    ),
  // --- inbox (employer replies to the managed apply alias) ---
  inbox: (limit = 20, offset = 0) =>
    request<InboxItem[]>(
      `/inbound/inbox?limit=${limit}${offset ? `&offset=${offset}` : ""}`,
    ),
  searchLocations: () =>
    request<{
      countries: { code: string; name: string }[];
      continents: { code: string; name: string; countries: string[] }[];
    }>("/jobs/search-locations"),
  editCoverLetter: (id: string, cover_letter: string) =>
    request<{ cover_letter: string | null }>(
      `/jobs/applications/${id}/cover-letter`,
      { method: "PUT", body: JSON.stringify({ cover_letter }) },
    ),
  regenerateCoverLetter: (id: string) =>
    request<{ cover_letter: string | null }>(
      `/jobs/applications/${id}/cover-letter/regenerate`,
      { method: "POST" },
    ),
  applyBatch: (count: number) =>
    request<{ queued: number; detail: string | null }>(
      "/jobs/applications/apply-batch",
      { method: "POST", body: JSON.stringify({ count }) },
    ),
  setAutoApply: (enabled: boolean) =>
    request<{ enabled: boolean }>("/jobs/auto-apply", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),
  setAutoCreate: (enabled: boolean) =>
    request<{ enabled: boolean }>("/account/auto-create-accounts", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),

  // --- automation (the standing search, not a one-off match run) ---
  getAutomation: () => request<AutomationStatus>("/jobs/automation"),
  setAutomation: (state: AutomationState) =>
    request<AutomationStatus>("/jobs/automation", {
      method: "POST",
      body: JSON.stringify({ state }),
    }),

  cancelMatching: () =>
    request<{ queued: number; detail: string | null }>("/jobs/match/cancel", {
      method: "POST",
    }),

  // --- interviews ---
  listInterviews: () => request<InterviewSummary[]>("/interviews"),
  createInterview: (body: {
    job_id?: string;
    job_description?: string;
    job_title?: string;
    job_company?: string;
    question_count?: number;
  }) =>
    request<InterviewDetail>("/interviews", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getInterview: (id: string) => request<InterviewDetail>(`/interviews/${id}`),
  transcribeAudio: async (blob: Blob) => {
    const form = new FormData();
    form.append("audio", blob, "answer.webm");
    return request<{ text: string }>("/interviews/transcribe", {
      method: "POST",
      body: form,
    });
  },
  submitAnswer: (sessionId: string, question_index: number, answer: string) =>
    request<Feedback>(`/interviews/${sessionId}/answer`, {
      method: "POST",
      body: JSON.stringify({ question_index, answer }),
    }),
  completeInterview: (id: string) =>
    request<InterviewDetail>(`/interviews/${id}/complete`, { method: "POST" }),
  deleteInterview: (id: string) =>
    request<void>(`/interviews/${id}`, { method: "DELETE" }),

  // --- account ---
  exportData: () => request<Record<string, unknown>>("/account/export"),
  deleteAccount: (body: { password?: string; confirm_email?: string }) =>
    request<void>("/account", { method: "DELETE", body: JSON.stringify(body) }),
};
