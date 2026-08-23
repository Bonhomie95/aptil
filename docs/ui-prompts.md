# Aptil — UI direction

The design brief behind the interface that ships today. The system lives in
`frontend/src/app/globals.css` (tokens) and `frontend/tailwind.config.ts`
(the names components use); **The prompt** at the bottom regenerates it.

---

## The thesis

**Aptil is a quiet instrument, not a dashboard.**

It works on your behalf while you're not looking, in a situation you're anxious
about. So the interface should feel like a well-made tool someone left running —
precise, legible, unhurried, and honest about what it is doing. Confidence comes
from restraint and typography, never from colour or effects.

**What that replaced:** purple→pink gradients, glassmorphism everywhere, glowing
shadows, drifting aurora blobs, a particle canvas. That palette read
"2021 AI startup". This product is asking people to trust it with their career.

---

## The decisions

**Near-monochrome warm grey. One blue, used only for information.**

```css
/* light */                        /* dark */
--color-background:  #fcf8fb;      #131215;   /* page canvas */
--color-card:        #fcf8fb;      #1a181c;   /* card, separated by a hairline */
--color-surface:     #ffffff;      #201d22;   /* raised: auth card, panel header */
--color-muted:       #f6f2f5;      #201d22;   /* stat tiles, a stalled row */
--color-tile:        #f0edf0;      #26232a;   /* icon tiles, switch track */
--color-foreground:  #1c1b1d;      #f4f0f3;
--color-muted-foreground: #434655;  #b9bcd0;
--color-subtle:      #5e5e67;      #94919c;
--color-border:      #c3c6d7;      #35323b;
--color-primary:     #1c1b1d;      #f4f0f3;  /* ACTION */
--color-accent:      #004ac6;      #94b8ff;  /* INFORMATION */
--color-accent-soft: #e0dee9;      #23293c;
--color-danger:      #ba1a1a;      #ffb4ab;
--color-positive:    #006d3c;      #6ddc9a;
--color-warn:        #bc4800;      #ffb599;
```

Every foreground/background pair is verified against WCAG AA in both themes.
Light: body ink 16.3:1, muted 8.9:1, subtle 6.1:1, accent 7.1:1 (5.7:1 on
`accent-soft`), danger 6.1:1, positive 6.1:1, warn 4.9:1, warn ink on warn
background 13.3:1. Dark: 16.5 / 9.9 / 6.0 / 9.4 / 7.3 / 11.0 / 11.0 / 11.0 /
12.8. The tightest pair is `warn` at 4.9:1 — it has 0.4 of headroom and nothing
more, so don't lighten it for "elegance".

The rule that makes this look expensive: **the primary button is near-black, not
accent-coloured.** `--primary` background, `--primary-foreground` text; in dark
it inverts to near-white rather than disappearing. The blue is reserved for
match scores, active nav, links, the brand mark, and focus rings — things that
carry *information*. A screen where the only blue is a score arc looks composed;
a screen with a blue button, blue links and blue badges looks like a template.

`primary` and `accent` are not interchangeable. That is the whole system.

**Two typefaces, with a hard boundary.**

- **Inter** — everything in the app. `font-feature-settings: 'cv11','ss01','tnum'`.
  `tnum` is not optional: every number in this product sits in a column
  (match %, quotas, scores) and proportional figures make them jitter.
- **Instrument Serif** — the marketing headline, the onboarding step title, and
  the interview question and score. Never for UI text, never for labels.

Scale: `12 · 14 · 16 · 18 · 24 · 32 · 44 · 60`. Body is 16. Tracking `-0.02em`
above 32px, `0` below. Weight does hierarchy: 400 body, 500 labels, 600 headings.

**Geometry.** Radius `8px` controls, `12px` cards, `4px` chips, full-round only
on the score arc and avatars. Border `1px solid --border` — hairlines, not
shadows. Shadow appears **only** on things that genuinely float: the auth card
(`--shadow-raised`), modals, popovers. A card sitting on a page does not float.

**Spacing** on an 8 grid: `4 8 12 16 24 32 48 64 96`. Related things 8 apart,
sections 48+. Whitespace is the hierarchy; reach for a gap before a divider.

**Motion.** One curve, `--ease: cubic-bezier(0.32, 0.72, 0, 1)`, 200ms.
Transform and opacity only. Nothing loops, pulses, or bounces, and **nothing the
user came to read waits on an animation** — the hero has no entrance transition
at all, because a paused rAF (a background tab) would leave it blank. Under
`prefers-reduced-motion`, motion is removed, not shortened.

---

## Three components that make it recognisably Aptil

All three live in `frontend/src/components/signals.tsx`.

**1. `<ScoreArc>`.** Match quality is a thin 2px arc around a tabular number —
not a coloured pill, not a progress bar. Grey below 70%, accent at 70%+. It is
the only circular thing on the screen, so it becomes the product's mark. Sizes:
40px in a row, 56px beside feedback, 64px on the marketing proof card.

**2. `<StatusRail>`.** A 2px vertical hairline down the left edge of each
application row, filled proportionally to how far that application has travelled
(matched → queued → submitted → confirmed → interview → offer). It replaces the
coloured status pills: the pipeline becomes readable by scanning one edge. The
early stages are deliberately grey — a page of "matched" rows is not progress.
A text `<StateLabel>` always rides alongside, so status never depends on colour.

**3. `<WorkingLine>`.** A 1px accent hairline travelling across the top of the
page whenever background work is running — searching for matches, parsing a CV,
scoring an answer. It replaces spinners for work the user did not synchronously
request, which is most of what this product does. The visual is `aria-hidden`
and a polite `role="status"` carries the words, so a screen reader hears
"Searching for new matches" once rather than every frame.

---

## Per screen, the one decision that matters

**Dashboard** — the hardest moment is a `needs_info` row. The user was promised
automation and is being asked to finish something. It is designed as *progress
that stalled*, not failure: `<StalledTicks>` shows what Aptil already filled in
(name, email, phone, résumé), then one concrete next step and a **Resume**
button. Warn hairline and warn chip, never red. Nothing failed.

**Onboarding** — six steps. "Leave and come back" has to be believable, so the
header carries a truthful save state (`Saved` / `Unsaved changes` / `Saving…`)
rather than a progress bar that means nothing. Step 3 (repeating work history)
is where naive designs break: the "add another" target is a full-width dashed
row, so the fifth entry is as easy as the first.

**Interview** — used while someone is nervous. One question on screen in the
serif, nothing competing. Voice is a single calm cluster: read aloud, a 64px
record button, auto-read toggle — no toolbar. The score returns in the serif,
large and unadorned; no confetti, no gauge.

**Settings** — an 8/4 split with everything irreversible pushed into its own
column behind a hairline, so a destructive control never sits beside a save
button. Revealing a stored password is the delicate flow: collapsed row →
account-password challenge → revealed secret → auto-hidden after 60s.

**Landing** — one editorial serif headline, then proof rather than adjectives:
the status rail and the score arc doing their actual job. Three honesty
constraints that are product requirements — the free tier is real, we never
imply CAPTCHA-solving or logging into anyone's LinkedIn (we apply through
official ATS forms and stop at every human check, and that restraint is a *trust
feature*), and any sample numbers say out loud that they are illustrative.

**Auth** — seen at 3am on a phone. Errors are the whole job: inline field errors
with an icon inside the input, an unverified-email state with a live resend
countdown, rate-limit and session-expired notices. Every message says what to do
next.

---

## The prompt

> Design **Aptil**, a job-application and interview-prep product. Direction:
> *a quiet instrument, not a dashboard* — it works on the user's behalf while
> they're not looking, in a situation they're anxious about. Confidence comes
> from restraint and typography, never colour or effects. Explicitly avoid
> gradients, glassmorphism, glow, and coloured badges: that reads "AI startup
> template" and this product handles people's careers.
>
> **Palette** — near-monochrome warm grey: bg `#fcf8fb`/`#131215`, surface
> `#ffffff`/`#201d22`, ink `#1c1b1d`/`#f4f0f3`, muted `#434655`/`#b9bcd0`, line
> `#c3c6d7`/`#35323b`, accent `#004ac6`/`#94b8ff`, plus green/amber/red for
> state. **The primary button is near-black (inverting to near-white in dark),
> not accent-coloured.** The accent is reserved for things carrying information
> — match scores, active nav, links, focus rings. Never for decoration.
>
> **Type** — Inter for all UI with `font-feature-settings: 'cv11','ss01','tnum'`
> (tabular figures are required; every number here sits in a column). Instrument
> Serif for exactly three things: the marketing headline, the onboarding step
> title, and the interview question and score. Scale 12/14/16/18/24/32/44/60,
> body 16, tracking -0.02em above 32px. Weight carries hierarchy: 400/500/600.
>
> **Geometry** — radius 8px controls, 12px cards, 4px chips, full-round only on
> score arcs and avatars. 1px hairline borders, not shadows. Shadows only on
> things that truly float (auth card, modal, popover). 8pt spacing:
> 4/8/12/16/24/32/48/64/96. Whitespace is the hierarchy — prefer a gap to a
> divider.
>
> **Motion** — one curve `cubic-bezier(0.32,0.72,0,1)` at 200ms, transform and
> opacity only. Nothing loops or bounces. No entrance animation on content the
> visitor came to read. `prefers-reduced-motion` removes motion, not shortens it.
>
> **Three signature components, design these first:**
> 1. *Score arc* — match % as a thin 2px arc around a tabular number. Grey below
>    70%, accent at 70%+. The only circular element on screen.
> 2. *Status rail* — a 2px vertical hairline on each application row, filled to
>    show pipeline position (matched → queued → submitted → interview → offer).
>    Replaces coloured status pills; keep a text label so status never depends on
>    colour alone, and keep early stages grey.
> 3. *Working line* — a 1px accent hairline travelling across the top of the page
>    whenever background work runs. Replaces every spinner.
>
> **Layout** — signed-in screens use a 256px left rail (drawer below 1024px) and
> a 12-column content grid, usually split 8/4. Marketing uses a 64px top bar with
> a hairline that only appears once scrolled.
>
> **Deliver** design tokens as CSS custom properties on `:root` with a `.dark`
> override, then these screens: Dashboard, Onboarding (6 steps), Interview
> (with voice controls), Settings, Landing, Auth.
>
> For every screen show **default, loading, empty, and error** states — and for
> the Dashboard specifically, the `needs_info` row, which must read as *progress
> that stalled*, not failure: show what was already filled in, then one concrete
> next step.
>
> Stack: Next.js App Router, TypeScript, Tailwind, semantic HTML with correct
> ARIA. WCAG AA in both themes — state the contrast ratios. Mobile-first;
> show 390px and 1440px.

---

## Two follow-ups worth sending

> Show every state side by side — default, loading, empty, error, disabled — plus
> the longest realistic content: a 90-character job title, a 40-character company
> name, a user with 12 applications.

> Redesign this at 390px. Don't stack the desktop layout — decide what earns a
> place on a small screen and what collapses behind a disclosure.

---

## Before you ship a redesign

Tokens live in `frontend/src/app/globals.css` as CSS custom properties, with
`tailwind.config.ts` naming them — a regenerated design system drops in without
touching components. `color-scheme` is set per theme, or native selects and
scrollbars render light on a dark page.

The browser suite still has to pass. It asserts labelled inputs, one `h1` per
page, a working skip link, no horizontal overflow at four viewports, AA contrast
on headings, and that reveal animations actually finish — a useful floor, since
generated UI tends to drop labels and focus rings. It also pins page headings,
nav labels and button names, so renaming copy is a deliberate act with a test to
update, not a silent drift.

```bash
cd backend && pytest tests/e2e -q
```
