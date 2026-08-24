"""Application configuration, loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholder values that must never survive into a production deployment.
_INSECURE_SECRETS = {
    "",
    "change-me",
    "change-me-openssl-rand-hex-32",
    "change-me-fernet-key",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- General ---
    ENVIRONMENT: str = "development"
    PROJECT_NAME: str = "Aptil"
    API_V1_PREFIX: str = "/api/v1"
    BACKEND_CORS_ORIGINS: str = "http://localhost:3000"
    # Public base URL of the web app. Used to build links in outgoing email and to
    # redirect back after OAuth. Kept separate from CORS origins on purpose.
    FRONTEND_BASE_URL: str = "http://localhost:3000"
    # Comma-separated CIDRs / IPs of trusted reverse proxies. Only when the direct
    # peer is in this list do we believe X-Forwarded-For (see core.ratelimit).
    TRUSTED_PROXY_IPS: str = ""

    # --- Security ---
    # Placeholder defaults keep local dev frictionless; _refuse_insecure_production
    # below hard-fails if they survive into a production boot.
    SECRET_KEY: str = "change-me"  # noqa: S105 - dev placeholder, validated below
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    CREDENTIAL_ENCRYPTION_KEY: str = ""
    # Retired key-encryption keys, comma-separated, newest first. Decrypt-only:
    # nothing is ever written under them. Rotation is: mint a new key, move the
    # old one here, restart, then run `python -m scripts.rotate_credential_key`.
    CREDENTIAL_ENCRYPTION_KEYS_OLD: str = ""
    # Rejected uploads above this size (bytes). Default 10 MiB.
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024

    # --- MongoDB ---
    MONGO_URL: str = "mongodb://mongo:27017"
    MONGO_DB: str = "aptil"

    # --- Redis ---
    REDIS_URL: str = "redis://redis:6379/0"

    # --- MinIO ---
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ROOT_USER: str = "aptil"
    MINIO_ROOT_PASSWORD: str = ""
    MINIO_BUCKET: str = "aptil-uploads"
    MINIO_SECURE: bool = False
    # Part of the SigV4 signature. MinIO ignores it; real S3 does not — a wrong
    # region gives SignatureDoesNotMatch. Leave MINIO_ENDPOINT empty to talk to
    # AWS S3 directly on this region's default endpoint.
    MINIO_REGION: str = "us-east-1"

    # --- Email ---
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "no-reply@aptil.ai"
    SMTP_TLS: bool = True

    # --- Google OAuth ---
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"

    # --- AI providers (comma-separated key pools) ---
    OPENAI_API_KEYS: str = ""
    ANTHROPIC_API_KEYS: str = ""
    XAI_API_KEYS: str = ""
    GROQ_API_KEYS: str = ""
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    LLM_DEFAULT_MODEL: str = "anthropic/claude-sonnet-5"
    LLM_FALLBACK_MODELS: str = "openai/gpt-4o-mini,groq/llama-3.3-70b-versatile"
    # Upper bound on questions per generated mock interview (cost guard).
    MAX_INTERVIEW_QUESTIONS: int = 20

    # --- Payments ---
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_SUCCESS_URL: str = "http://localhost:3000/billing/success"
    STRIPE_CANCEL_URL: str = "http://localhost:3000/billing/cancel"

    # --- Job sources ---
    ADZUNA_APP_ID: str = ""
    ADZUNA_APP_KEY: str = ""

    # --- Web-search discovery (the primary, aggregator-independent source) ---
    # Finds job postings across the OPEN WEB via a real search API — never by
    # scraping a search engine's result page (bot-detection evasion, gets the
    # host banned). Provider is pluggable:
    #   serper  - 2,500 free searches, no card (default; easiest start)
    #   tavily  - 1,000 free credits/month, no card
    #   searxng - self-hosted, keyless, UNLIMITED (set WEB_SEARCH_ENDPOINT to
    #             your instance's /search; no API key needed)
    #   brave   - requires a card
    # WEB_SEARCH_ENDPOINT is optional: each provider has a sensible default;
    # override only for self-hosting (searxng) or a proxy.
    WEB_SEARCH_PROVIDER: str = "serper"
    WEB_SEARCH_API_KEY: str = ""
    WEB_SEARCH_ENDPOINT: str = ""
    # Turn the whole web-search source on/off.
    SOURCING_WEB_SEARCH: bool = True
    # Keep Adzuna as an ADDITIONAL source, or turn it off entirely. Off by
    # default now that web search is the primary, web-wide discovery path.
    SOURCING_USE_ADZUNA: bool = False
    # Free remote-job boards (RemoteOK, Remotive) as ADDITIONAL sources. They
    # need no API key. Results pass the same per-user role/country/dedupe gates,
    # so enabling them only widens coverage, it cannot pollute a user's list.
    SOURCING_REMOTE_BOARDS: bool = True
    USAJOBS_API_KEY: str = ""
    USAJOBS_USER_AGENT: str = ""  # a registered contact email, per USAJOBS API rules

    # --- Matching quality ---
    # Applications are only created for jobs scoring at or above this. Raising it
    # gives fewer, better matches; lowering it gives more, weaker ones.
    MIN_MATCH_SCORE: float = 0.55
    # No single employer may take more than this many of one matching run's
    # results. Without it, whichever board has the most postings dominates the
    # user's whole dashboard.
    MAX_MATCHES_PER_COMPANY: int = 3
    # Cap on how many postings one connector run contributes, so a single large
    # board cannot swamp the shared pool.
    MAX_POSTINGS_PER_SOURCE: int = 300

    # --- Scheduler (Celery beat) ---
    # Set to 0 to disable a periodic job entirely.
    SOURCING_INTERVAL_MINUTES: int = 60
    MATCHING_INTERVAL_MINUTES: int = 30
    APPLY_INTERVAL_MINUTES: int = 15
    # JSON list of connector queries run on each sourcing tick, e.g.
    # [{"source": "greenhouse", "query": {"board": "stripe"}}]
    SOURCING_JOBS_JSON: str = "[]"
    # Ceiling on aggregator queries per sweep, so a few hundred users with
    # distinct target titles cannot turn one tick into a thundering herd.
    MAX_DEMAND_QUERIES: int = 40
    # Default country for aggregator search when a user has no location set.
    DEFAULT_JOB_COUNTRY: str = "us"

    # --- Managed apply email + account creation ---
    # Domain for per-user apply aliases (u-<id>@<domain>). Point Cloudflare
    # Email Routing's catch-all at the inbound webhook (infra/email/). Empty
    # disables aliases AND auto-registration — without an inbox we could not
    # verify the accounts we created.
    APPLY_EMAIL_DOMAIN: str = ""
    # HMAC key for the inbound-email webhook. Required when the domain is set.
    INBOUND_EMAIL_SECRET: str = ""
    # Whether new users default to letting Aptil create job-site accounts for
    # them using their managed alias. Users can turn it off in Settings.
    AUTO_CREATE_ACCOUNTS_DEFAULT: bool = True

    # --- Derived ---
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.BACKEND_CORS_ORIGINS.split(",") if o.strip()]

    @property
    def frontend_base_url(self) -> str:
        """Canonical web-app origin, with any trailing slash removed."""
        base = (self.FRONTEND_BASE_URL or "").strip().rstrip("/")
        if base:
            return base
        # Fall back to the first CORS origin, then to the dev default, so a link is
        # always constructible even in a half-configured environment.
        origins = self.cors_origins
        return origins[0].rstrip("/") if origins else "http://localhost:3000"

    @property
    def trusted_proxy_ips(self) -> list[str]:
        return [p.strip() for p in self.TRUSTED_PROXY_IPS.split(",") if p.strip()]

    @property
    def retired_credential_keys(self) -> list[str]:
        """Old KEKs, decrypt-only. Never used to encrypt anything new."""
        return [
            k.strip()
            for k in self.CREDENTIAL_ENCRYPTION_KEYS_OLD.split(",")
            if k.strip()
        ]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def sourcing_jobs(self) -> list[dict]:
        """Parsed SOURCING_JOBS_JSON; an invalid value degrades to no jobs."""
        import json

        try:
            parsed = json.loads(self.SOURCING_JOBS_JSON or "[]")
        except ValueError:
            return []
        return [j for j in parsed if isinstance(j, dict) and j.get("source")]

    def key_pool(self, raw: str) -> list[str]:
        return [k.strip() for k in raw.split(",") if k.strip()]

    @model_validator(mode="after")
    def _warn_on_truncated_secrets(self) -> Settings:
        """Catch values mangled by docker-compose variable interpolation.

        Compose substitutes `$NAME` inside .env values, so a secret containing a
        literal `$` silently arrives truncated — SMTP or Stripe then fail with an
        opaque "authentication failed" and nothing points at the cause. A `$$`
        that survived into the runtime value means the escape was not consumed,
        which is the other half of the same footgun.
        """
        import warnings

        for name in (
            "SMTP_PASSWORD",
            "STRIPE_SECRET_KEY",
            "MINIO_ROOT_PASSWORD",
            "SECRET_KEY",
            "CREDENTIAL_ENCRYPTION_KEY",
        ):
            value = getattr(self, name, "") or ""
            if "$$" in value:
                warnings.warn(
                    f"{name} still contains '$$'. In .env a literal '$' must be "
                    "written '$$' for docker compose, but it should be consumed "
                    "before reaching the app — this value is probably wrong.",
                    stacklevel=2,
                )
        return self

    @model_validator(mode="after")
    def _refuse_insecure_production(self) -> Settings:
        """Fail fast rather than run production on placeholder secrets."""
        if self.ENVIRONMENT != "production":
            return self
        problems: list[str] = []
        if self.SECRET_KEY.strip() in _INSECURE_SECRETS:
            problems.append("SECRET_KEY is unset or still the placeholder value")
        if self.CREDENTIAL_ENCRYPTION_KEY.strip() in _INSECURE_SECRETS:
            problems.append(
                "CREDENTIAL_ENCRYPTION_KEY is unset or still the placeholder value"
            )
        if len(self.SECRET_KEY.strip()) < 32:
            problems.append("SECRET_KEY must be at least 32 characters")
        if not self.MINIO_ROOT_PASSWORD.strip():
            problems.append("MINIO_ROOT_PASSWORD is not set")
        if not self.SMTP_HOST.strip():
            problems.append(
                "SMTP_HOST is not set — verification emails would only be logged"
            )
        # The compose defaults resolve inside the dev network and nowhere else.
        # Reaching production with them means the app silently talks to nothing.
        if self.MONGO_URL.strip() in {"", "mongodb://mongo:27017"}:
            problems.append("MONGO_URL is still the local docker-compose default")
        if self.FRONTEND_BASE_URL.strip().startswith("http://localhost"):
            problems.append(
                "FRONTEND_BASE_URL still points at localhost — every link in "
                "outgoing email would be unreachable"
            )
        if not self.TRUSTED_PROXY_IPS.strip():
            # Not fatal, but every visitor shares one rate-limit bucket.
            log_only = (
                "TRUSTED_PROXY_IPS is unset. Behind a proxy, every visitor "
                "shares one rate-limit bucket."
            )
            import warnings

            warnings.warn(log_only, stacklevel=2)
        if problems:
            raise ValueError(
                "Refusing to start in production with insecure configuration: "
                + "; ".join(problems)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
