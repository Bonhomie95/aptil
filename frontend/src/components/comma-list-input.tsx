"use client";

import { useEffect, useId, useRef, useState } from "react";

/**
 * Text input for a comma-separated list that emits string[].
 *
 * Why this exists: the naive pattern `value={arr.join(", ")}` with an onChange
 * that splits+filters re-derives the input's value from the parsed array on
 * every keystroke. `filter(Boolean)` then drops the empty element created the
 * instant you type a comma — so the comma is erased before the next character,
 * making multi-item entry impossible.
 *
 * The fix: the raw text is the source of truth in local state. We parse to an
 * array for the parent, but never rebuild the text FROM the array while the
 * user is typing — so commas (and spaces) survive.
 */

function parse(text: string, max: number): string[] {
  const out: string[] = [];
  for (const raw of text.split(",")) {
    const v = raw.trim();
    if (v && !out.some((x) => x.toLowerCase() === v.toLowerCase())) out.push(v);
    if (out.length >= max) break;
  }
  return out;
}

export function CommaListInput({
  label,
  value,
  onChange,
  hint,
  placeholder,
  max = 20,
}: {
  label: string;
  value: string[];
  onChange: (next: string[]) => void;
  hint?: string;
  placeholder?: string;
  max?: number;
}) {
  const id = useId();
  const [text, setText] = useState(value.join(", "));
  const focused = useRef(false);

  // Re-sync from props only when the field is NOT focused (e.g. the profile
  // loaded from the server after mount). While typing, local text wins, so a
  // comma is never stripped out from under the cursor.
  useEffect(() => {
    if (!focused.current) setText(value.join(", "));
  }, [value]);

  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        value={text}
        placeholder={placeholder}
        aria-describedby={hint ? `${id}-hint` : undefined}
        onFocus={() => {
          focused.current = true;
        }}
        onBlur={() => {
          focused.current = false;
          setText(value.join(", ")); // normalise display once editing ends
        }}
        onChange={(e) => {
          setText(e.target.value);
          onChange(parse(e.target.value, max));
        }}
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
