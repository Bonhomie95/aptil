# Compliance & safety guardrails

These are product constraints, not suggestions. They protect users' accounts, keep the
business legally defensible, and are wired into the architecture. Read before touching the
apply engine or the interview copilot.

## 1. Apply through official channels, not by impersonating logged-in sessions

- **Do:** discover jobs via official APIs / public ATS endpoints / job feeds (Adzuna,
  Greenhouse, Lever, Ashby, Workday, USAJOBS). Apply through the company's own ATS
  application form, or via a user-present browser-extension autofill.
- **Don't:** pilot a user's logged-in LinkedIn/Indeed session to auto-apply. It violates
  those platforms' Terms of Service, has been litigated (esp. LinkedIn), and gets user
  accounts banned at scale.

## 1a. Sign in with a stored credential — never sign up

- **Do:** where an ATS hides the application form behind a sign-in (Workday, iCIMS,
  Taleo), sign in with the credential the user stored for *that exact host*
  (`SiteCredential`, matched by hostname in `apply.py::_credential_for`). The user
  creates the account themselves. See `AtsAdapter.perform_login`.
- **Don't:** create an account on a third party's site. There is deliberately no
  registration code path, and `tests/test_credentials_and_login.py` fails if an adapter
  grows a `register`/`signup` method. Three reasons, in order of weight:
  1. Most ATS terms prohibit automated account creation. Applying through a public form
     is defensible; creating accounts is not.
  2. Signup is where bot detection is heaviest, so it would park constantly anyway.
  3. It would leave Aptil holding working credentials to accounts the user never chose
     to create — a much larger blast radius than storing a password for one they did.
- A login is attempted **once**. Wrong password, an MFA prompt, or a changed layout all
  park the application (`login_failed`); we never retry, because guessing repeatedly is
  how an account gets locked.
- Sign-in success needs positive proof (a sign-out control on the page), for the same
  reason section 2a requires it for submission: a clicked button proves nothing.

## 2. Never bypass CAPTCHAs or bot-detection

- If an application flow presents a CAPTCHA or bot-check, the apply engine parks the
  application in `NEEDS_INFO` for the user to finish manually. See
  `app/workers/tasks/apply.py`. We do not build, integrate, or call CAPTCHA-solving.
- Detection runs three times per attempt: after load, immediately before the submit click,
  and on the confirmation page. See `app/services/ats/base.py`.

## 2a. Never claim a submission we cannot evidence

- `submitted` is only recorded when the ATS confirmation page actually says so. A clicked
  button proves nothing: client-side validation can reject a form silently, and reporting
  those as successes would tell users we applied to jobs we never applied to. Anything
  unconfirmed is parked in `NEEDS_INFO` with the reason.
- Required fields (contact email, name) are checked *before* submitting. An application an
  employer cannot reply to is worse than no application.
- `submitted` is not a status a user can set by hand either (`USER_SETTABLE_STATUSES` in
  `app/api/v1/routes/jobs.py`). The dashboard's status picker renders it as a disabled
  current value, never as a choice, so nobody can manufacture a record of an application
  that was never sent. `tests/test_security.py` pins the API side of that.

## 3. Credentials are encrypted, unique per site, never plaintext

- One reused password across many sites is prohibited. `SiteCredential` stores a
  **per-site** secret. If the user doesn't supply one, we generate a unique strong one.
- **Envelope encryption.** A random data key encrypts the password; `CREDENTIAL_ENCRYPTION_KEY`
  encrypts that data key. Stored as `v2.<key id>.<wrapped data key>.<ciphertext>`. One
  data key per secret, so compromising a data key exposes exactly one credential — and
  rotation re-wraps 32 bytes per row instead of decrypting and re-encrypting the table.
  See `app/core/security.py`.
- **Rotation is a supported operation, not a migration project:**

  ```
  # 1. mint a new key
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  # 2. CREDENTIAL_ENCRYPTION_KEY=<new>, CREDENTIAL_ENCRYPTION_KEYS_OLD=<previous>
  # 3. restart api + workers, then:
  python -m scripts.rotate_credential_key            # dry run: how many rows are stale
  python -m scripts.rotate_credential_key --apply
  # 4. once it reports zero remaining, clear CREDENTIAL_ENCRYPTION_KEYS_OLD
  ```

  Retired keys are **decrypt-only** — nothing is ever written under them. Pre-envelope
  rows still decrypt and are upgraded in place by the same run.
- Reading a secret back requires re-entering the **account** password
  (`POST /credentials/{id}/reveal`), is rate limited to 10/hour per user, and is written
  to the audit log. A stolen session token is not enough.
- Still open before scaling: move the key-encryption key into a real KMS/HSM so it is
  never a plain env var, and document key custody. The envelope format is already the
  right shape for that — only `_primary_kek()` changes.

## 4. Interview feature = practice, with consent

- The interview copilot runs **mock/practice** sessions grounded in the user's CV and the
  target job. It generates questions, captures answers, and gives feedback.
- We do **not** covertly intercept or record live third-party interview calls. Real-time
  interception without all-party consent is illegal in many jurisdictions (two-party-consent
  wiretap laws) and facilitates deceiving an employer. The Phase-2 desktop copilot assists
  **practice sessions** with global hotkeys and low-latency audio.

## 5. Data protection (PII)

- CVs and profiles are personal data. Implemented:
  - **Terms/Privacy at signup** — `/terms`, `/privacy`, and a required consent checkbox on
    registration. Acceptance is recorded on `User.accepted_terms_at`.
  - **Data export** — `GET /api/v1/account/export` returns everything held for the caller
    as JSON (secrets excluded), surfaced in Settings.
  - **Account deletion** — `DELETE /api/v1/account` removes the profile, résumés (including
    the objects in MinIO), credentials, applications, interviews and subscription, then the
    user and tenant.
  - **Encryption at rest** for site credentials (Fernet); passwords are Argon2id hashes.
- Multi-tenant isolation is enforced in the application layer: every tenant-scoped query
  filters by `tenant_id` (or the owning `user_id`). MongoDB has no Row-Level Security, so
  this discipline IS the boundary — never issue a tenant-scoped read/write without the filter.

## 6. Be a polite automated client

- Respect robots/rate limits on any site we touch; back off on errors; identify honestly
  (the apply engine's User-Agent names the bot and links to a policy page).
- Rate-limit our own endpoints to prevent abuse of the platform itself. Applied to every
  auth endpoint, uploads, interview creation, checkout, matching and apply — see
  `app/core/ratelimit.py`. Expensive per-account endpoints bucket by user, not just IP.
- Apply at most two applications concurrently per user, and never twice to the same
  fingerprinted role.

## 7. AI inputs are untrusted

- Job descriptions come from third-party boards and CV text from user uploads. Both are
  fenced inside explicit data delimiters with an instruction never to follow directions
  found inside them (`app/ai/prompts.py`), so a posting containing "ignore your
  instructions" cannot steer résumé tailoring or interview scoring.
- Provider API keys are redacted from any error text before it reaches a log.
