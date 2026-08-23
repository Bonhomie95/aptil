"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

// Server snapshot false, client snapshot true: tells us we have hydrated without
// an effect that sets state (which triggers a cascading render).
const subscribe = () => () => {};
const useMounted = () =>
  useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useMounted();
  const isDark = resolvedTheme === "dark";

  return (
    <button
      type="button"
      aria-label={
        mounted
          ? `Switch to ${isDark ? "light" : "dark"} theme`
          : "Toggle color theme"
      }
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors duration-200 ease-ease hover:bg-muted hover:text-foreground"
    >
      {mounted ? (
        isDark ? (
          <Sun className="h-4 w-4" aria-hidden />
        ) : (
          <Moon className="h-4 w-4" aria-hidden />
        )
      ) : (
        // Placeholder keeps the button the same size before hydration.
        <span className="h-4 w-4" />
      )}
    </button>
  );
}
