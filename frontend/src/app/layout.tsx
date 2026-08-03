import type { Metadata } from "next";
import { Barlow, Barlow_Condensed, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";
import { Sidebar } from "@/components/layout/sidebar";
import { MainShell } from "@/components/layout/main-shell";

/* Pairing "Sports/Fitness" del rediseño broadcast (ver Rediseno UIX 2026 en el vault).
 * Barlow trae numerales tabulares, que es lo que evita que una cuota "baile" de ancho
 * cuando se actualiza en vivo -- por eso este par y no Inter/Space Grotesk. */
const barlow = Barlow({
  variable: "--font-sans",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
});

const barlowCondensed = Barlow_Condensed({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const geistMono = Geist_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Claim — apuestas de torneo",
  description:
    "Claim: mercados de predicción en vivo sobre torneos de debate BP. Se juega con tokens, cero dinero real.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="es"
      className={`dark ${barlow.variable} ${barlowCondensed.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-background text-foreground">
        <Providers>
          <div className="flex min-h-screen">
            <Sidebar />
            <MainShell>{children}</MainShell>
          </div>
        </Providers>
      </body>
    </html>
  );
}
