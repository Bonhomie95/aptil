import type { Metadata } from "next";
import { Inter, Instrument_Serif } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import "./globals.css";

const body = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-body",
  display: "swap",
});

// One serif moment per surface: the marketing headline and the interview
// score. Loaded at a single weight because it is never used for UI text.
//
// preload: false because the variable is declared on <html> for every route,
// so Next preloaded it everywhere while only a handful of pages render a serif
// glyph — the browser then warns "preloaded ... but not used within a few
// seconds" on most page loads, and the fetch is wasted. It still self-hosts and
// still loads where it is actually used; `swap` plus the fallback below means
// no invisible text while it does.
const display = Instrument_Serif({
  subsets: ["latin"],
  weight: ["400"],
  variable: "--font-display",
  display: "swap",
  preload: false,
  fallback: ["ui-serif", "Georgia", "serif"],
});

export const metadata: Metadata = {
  title: "Aptil — Land the job, ace the interview",
  description:
    "AI-powered job applications and interview prep, grounded in your real CV and the exact role you're targeting.",
  metadataBase: new URL("https://aptil.ai"),
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning className={`${body.variable} ${display.variable}`}>
      <body>
        {/* Entrance animations render `opacity: 0` into the SSR markup. Without
            JS that would hide the page content for good, so force it visible. */}
        <noscript
          // Raw HTML rather than children: React refuses to run markup nested
          // inside <noscript> during a client render and warns about it.
          dangerouslySetInnerHTML={{
            __html:
              '<style>[style*="opacity:0"],[style*="opacity: 0"]' +
              "{opacity:1!important;transform:none!important}</style>",
          }}
        />
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
