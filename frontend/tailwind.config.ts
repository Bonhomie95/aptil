import type { Config } from "tailwindcss";

/**
 * Colours are CSS custom properties (see globals.css) so the light/dark swap
 * happens in one place and a regenerated design system drops in without
 * touching a single component.
 *
 * Naming carries the rule: `primary` is the near-black action colour and
 * `accent` is the blue information colour. They are not interchangeable.
 */
const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--color-background)",
        foreground: "var(--color-foreground)",
        card: "var(--color-card)",
        surface: "var(--color-surface)",
        muted: "var(--color-muted)",
        tile: "var(--color-tile)",
        "muted-foreground": "var(--color-muted-foreground)",
        subtle: "var(--color-subtle)",
        border: "var(--color-border)",
        primary: {
          DEFAULT: "var(--color-primary)",
          foreground: "var(--color-on-primary)",
        },
        accent: {
          DEFAULT: "var(--color-accent)",
          foreground: "var(--color-on-accent)",
          soft: "var(--color-accent-soft)",
        },
        danger: "var(--color-danger)",
        positive: "var(--color-positive)",
        warn: {
          DEFAULT: "var(--color-warn)",
          bg: "var(--color-warn-bg)",
          foreground: "var(--color-warn-foreground)",
        },
      },
      fontFamily: {
        sans: ["var(--font-body)", "ui-sans-serif", "system-ui", "sans-serif"],
        // Instrument Serif. Reserved for two moments: the marketing headline
        // and an interview score. A third use makes it decoration.
        display: ["var(--font-display)", "ui-serif", "Georgia", "serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      // 8px controls, 12px cards, 4px chips. Full-round only on score arcs
      // and avatars, which Tailwind's `rounded-full` already covers.
      borderRadius: {
        DEFAULT: "8px",
        sm: "4px",
        md: "6px",
        lg: "8px",
        xl: "12px",
        "2xl": "16px",
      },
      boxShadow: {
        raised: "var(--shadow-raised)",
        card: "var(--shadow-card)",
        float: "var(--shadow-float)",
      },
      transitionTimingFunction: {
        ease: "var(--ease)",
      },
      keyframes: {
        "working-line": {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(100%)" },
        },
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: {
        // Both keyframes are also declared in globals.css, because rules there
        // use the raw `animation` property and Tailwind only emits @keyframes
        // for animations whose utility class appears in scanned source.
        "working-line": "working-line 1.6s var(--ease) infinite",
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [],
};

export default config;
