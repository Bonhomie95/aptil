"use client";

import { useId } from "react";
import type { Demographics } from "@/lib/api";

/**
 * Voluntary EEO self-identification, shared by onboarding and settings.
 *
 * Shared deliberately rather than duplicated: these values must match the API
 * enums exactly, and the wizard cannot be reused for editing — re-entering it
 * sets `onboarding_completed = false`, which drops the user out of the
 * automation sweep and silently stops their job search.
 */

export const DECLINE = "decline_to_self_identify";

export const GENDER_OPTIONS = [
  ["male", "Male"],
  ["female", "Female"],
  ["non_binary", "Non-binary"],
  [DECLINE, "Decline to self-identify"],
] as const;

export const YES_NO_OPTIONS = [
  ["yes", "Yes"],
  ["no", "No"],
  [DECLINE, "Decline to self-identify"],
] as const;

/** EEO-1 categories. "(Not Hispanic or Latino)" is part of the official
 *  category name, not decoration: Hispanic/Latino is collected as ethnicity and
 *  takes precedence over race on the EEO-1 report. */
export const RACE_OPTIONS = [
  ["hispanic_or_latino", "Hispanic or Latino"],
  ["white", "White (Not Hispanic or Latino)"],
  ["black_or_african_american", "Black or African American (Not Hispanic or Latino)"],
  [
    "native_hawaiian_or_pacific_islander",
    "Native Hawaiian or Other Pacific Islander (Not Hispanic or Latino)",
  ],
  ["asian", "Asian (Not Hispanic or Latino)"],
  [
    "american_indian_or_alaska_native",
    "American Indian or Alaska Native (Not Hispanic or Latino)",
  ],
  ["two_or_more_races", "Two or More Races (Not Hispanic or Latino)"],
  [DECLINE, "Decline to self-identify"],
] as const;

export const VETERAN_OPTIONS = [
  ["protected_veteran", "I identify as one or more classifications of protected veteran"],
  ["not_a_veteran", "I am not a protected veteran"],
  [DECLINE, "Decline to self-identify"],
] as const;

/** The four VEVRAA classifications (38 U.S.C. 4212). Several can apply at once
 *  — a disabled veteran discharged last year is both disabled and recently
 *  separated — so these are checkboxes, not a choice. */
export const VETERAN_CATEGORY_OPTIONS = [
  ["disabled_veteran", "Disabled veteran"],
  [
    "recently_separated_veteran",
    "Recently separated veteran (discharged within the last 3 years)",
  ],
  [
    "active_duty_wartime_or_campaign_badge_veteran",
    "Active duty wartime or campaign badge veteran",
  ],
  ["armed_forces_service_medal_veteran", "Armed forces service medal veteran"],
] as const;

/** OFCCP Form CC-305 (OMB 1250-0005, expires 07/31/2029). A standardized
 *  federal form — the three options are fixed and shown verbatim. */
export const DISABILITY_OPTIONS = [
  ["yes", "Yes, I have a disability, or have had one in the past"],
  ["no", "No, I do not have a disability and have not had one in the past"],
  ["do_not_want_to_answer", "I do not want to answer"],
] as const;

/** Examples the CC-305 itself lists, to help people judge what counts.
 *  Reference text only — never stored. */
export const CC305_EXAMPLES =
  "Alcohol or substance use disorder, autism, blindness or low vision, cancer, " +
  "cardiovascular or heart disease, celiac disease, cerebral palsy, deaf or hard " +
  "of hearing, depression or anxiety, diabetes, epilepsy, gastrointestinal " +
  "disorders, intellectual or developmental disability, missing limbs or partially " +
  "missing limbs, mobility impairment, nervous system condition, neurodivergence, " +
  "partial or complete paralysis, pulmonary or respiratory conditions, short " +
  "stature, traumatic brain injury, and many others.";

export function DisclosureSelect({
  label,
  value,
  onChange,
  options,
  hint,
}: {
  label: string;
  value?: string | null;
  onChange: (v: string) => void;
  options: readonly (readonly [string, string])[];
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
        <option value="">Leave unanswered</option>
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
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

export function VoluntaryDisclosures({
  value,
  onChange,
}: {
  value: Demographics | null | undefined;
  /** Receives a PATCH of changed fields, never the whole object, so a caller
   *  merging into wider state cannot drop the answers it wasn't given. */
  onChange: (patch: Partial<Demographics>) => void;
}) {
  const d = value ?? {};
  const categories = d.veteran_categories ?? [];

  return (
    <div className="space-y-5">
      <DisclosureSelect
        label="Gender"
        value={d.gender}
        onChange={(v) => onChange({ gender: v || null })}
        options={GENDER_OPTIONS}
      />
      <DisclosureSelect
        label="Are you Hispanic or Latino?"
        value={d.hispanic_or_latino}
        onChange={(v) => onChange({ hispanic_or_latino: v || null })}
        options={YES_NO_OPTIONS}
        hint="Asked separately from race because the EEO-1 report treats Hispanic or Latino as an ethnicity."
      />
      <DisclosureSelect
        label="Race / ethnicity"
        value={d.race}
        onChange={(v) => onChange({ race: v || null })}
        options={RACE_OPTIONS}
      />

      <div className="space-y-3">
        <DisclosureSelect
          label="Veteran status"
          value={d.veteran_status}
          onChange={(v) =>
            onChange({
              veteran_status: v || null,
              // Classifications only mean anything alongside a "protected
              // veteran" answer; clear them otherwise so the two can never
              // contradict each other on a form.
              veteran_categories: v === "protected_veteran" ? categories : [],
            })
          }
          options={VETERAN_OPTIONS}
        />
        {d.veteran_status === "protected_veteran" && (
          <fieldset className="rounded-lg border border-border p-4">
            <legend className="px-1 text-sm font-medium">
              Which classifications apply?
            </legend>
            <p className="mb-3 text-xs text-muted-foreground">
              Tick all that apply — more than one often does. Some employers ask
              for these individually.
            </p>
            <div className="space-y-2">
              {VETERAN_CATEGORY_OPTIONS.map(([v, text]) => {
                const checked = categories.includes(v);
                return (
                  <label
                    key={v}
                    className="flex cursor-pointer items-start gap-3 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() =>
                        onChange({
                          veteran_categories: checked
                            ? categories.filter((c) => c !== v)
                            : [...categories, v],
                        })
                      }
                      className="mt-0.5 h-4 w-4 shrink-0 rounded border-border accent-accent"
                    />
                    <span>{text}</span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        )}
      </div>

      <div className="space-y-3">
        <DisclosureSelect
          label="Disability status"
          value={d.disability_status}
          onChange={(v) => onChange({ disability_status: v || null })}
          options={DISABILITY_OPTIONS}
        />
        <details className="rounded-lg border border-border bg-muted/30 p-4 text-sm">
          <summary className="cursor-pointer font-medium">
            How do I know if I have a disability?
          </summary>
          <div className="mt-3 space-y-2 text-muted-foreground">
            <p>
              You are considered to have a disability if you have a physical or
              mental impairment or medical condition that substantially limits a
              major life activity, or if you have a history or record of such an
              impairment or medical condition.
            </p>
            <p>Disabilities include, but are not limited to:</p>
            <p>{CC305_EXAMPLES}</p>
            <p className="text-xs">
              Wording follows OFCCP Form CC-305 (OMB Control Number 1250-0005,
              expires 07/31/2029), the standardized federal form employers use
              for this question.
            </p>
          </div>
        </details>
      </div>
    </div>
  );
}
