import type { Metadata } from "next";
import { Inter, Space_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";

/**
 * Two faces, deliberately different jobs.
 *
 * Space Grotesk carries the Zone A narrative: it has enough character to make a
 * hero headline and a large count-up number feel designed rather than defaulted.
 * Inter carries Zone B, where the console is read continuously at 12-14px and
 * legibility under sustained use matters more than personality. JetBrains Mono
 * is reserved for evidence payloads and raw values.
 */
const display = Space_Grotesk({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  display: "swap",
});

const ui = Inter({
  variable: "--font-ui",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

const mono = JetBrains_Mono({
  variable: "--font-mono-face",
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Ninja — digital twin of a vehicle assembly line",
  description:
    "Predicts assembly-line bottlenecks and defect escapes before they surface. " +
    "Median 37 minutes of lead time before a queue forms, on sealed holdout scenarios.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${ui.variable} ${mono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-bg text-fg">{children}</body>
    </html>
  );
}
