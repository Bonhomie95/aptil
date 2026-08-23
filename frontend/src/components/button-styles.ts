/**
 * Button styling, in a module with no "use client" directive so Server
 * Components can call it too (a function exported from a client module cannot
 * be invoked on the server).
 *
 * The primary button is near-black, not accent-coloured. That single rule is
 * what keeps the accent meaningful: blue on this product means "this carries
 * information" (a score, the active page, a focus ring), never "this is a
 * button". Radius is 8px on controls, 12px on cards, 4px on chips.
 */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-primary text-primary-foreground hover:opacity-90 disabled:hover:opacity-100",
  secondary:
    "border border-border bg-card text-foreground hover:border-foreground/40 hover:bg-muted",
  ghost: "text-muted-foreground hover:bg-muted hover:text-foreground",
  danger: "border border-danger/40 bg-transparent text-danger hover:bg-danger/10",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 rounded-sm px-2.5 text-xs",
  // 40px: comfortably above the 44px touch target once the 8px gap around it
  // is counted, and it matches the 40px input height on desktop.
  md: "h-10 gap-2 rounded-lg px-4 text-sm",
  lg: "h-12 gap-2 rounded-lg px-6 text-sm",
};

export function buttonClass(
  variant: ButtonVariant = "primary",
  size: ButtonSize = "md",
  extra = "",
) {
  return [
    "inline-flex items-center justify-center whitespace-nowrap font-medium",
    "transition-colors duration-200 ease-ease",
    "disabled:cursor-not-allowed disabled:opacity-50",
    SIZES[size],
    VARIANTS[variant],
    extra,
  ].join(" ");
}
