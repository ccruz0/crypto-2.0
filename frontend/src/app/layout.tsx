import type { Metadata } from "next";
import "./globals.css";

// Using system fonts instead of Google fonts to avoid Turbopack issues
const geistSans = { variable: "--font-geist-sans" };
const geistMono = { variable: "--font-geist-mono" };

export const metadata: Metadata = {
  title: "Trading Dashboard",
  description: "Automated Trading Platform Dashboard",
  // Prevent caching of the page
  other: {
    'Cache-Control': 'no-cache, no-store, must-revalidate',
    'Pragma': 'no-cache',
    'Expires': '0',
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body 
        className={`${geistSans.variable} ${geistMono.variable} bg-white text-gray-900 dark:bg-slate-900 dark:text-slate-100 antialiased`}
        suppressHydrationWarning
      >
        {children}
      </body>
    </html>
  );
}
