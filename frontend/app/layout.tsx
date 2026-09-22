import type { Metadata } from "next";
import { Geist, Geist_Mono, Newsreader } from "next/font/google";
import { AppShell } from "@/components/AppShell";
import { AuthProvider } from "@/lib/auth-context";
import "./globals.css";

// Design-system migration (TALYNT LABS website parity): the website's own
// exact typeface trio — Geist (sans, UI text), Geist Mono (labels/numbers/
// mono-micro eyebrows), Newsreader (display serif, italic for emphasis
// inside headlines). Replaces the prior Inter/Fraunces pairing.
const geist = Geist({
  variable: "--font-geist",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Page/section headlines only, never body or data — same restraint as the
// prior Fraunces usage, now the website's actual display face.
const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  style: ["normal", "italic"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Talyn",
  description: "AI-assisted GTM recruiting sourcing workflow — the recruiter stays the decision-maker.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      data-theme="dark"
      className={`${geist.variable} ${geistMono.variable} ${newsreader.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-background text-foreground">
        <AuthProvider>
          <AppShell>{children}</AppShell>
        </AuthProvider>
      </body>
    </html>
  );
}
