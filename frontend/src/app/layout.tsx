import type { Metadata } from "next";
import { Manrope, Sora } from "next/font/google";
import type { ReactNode } from "react";

import { themeInitScript } from "@/lib/theme";

import "./globals.css";

const manrope = Manrope({
  subsets: ["latin"],
  variable: "--font-body",
});

const sora = Sora({
  subsets: ["latin"],
  variable: "--font-display",
});

export const metadata: Metadata = {
  title: "MedSpeak",
  description: "Upload a medical visit audio file, turn it into clear notes, and ask grounded follow-up questions.",
  icons: {
    icon: "/Images/logo.png",
    apple: "/Images/logo.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className={`${manrope.variable} ${sora.variable}`}>{children}</body>
    </html>
  );
}
