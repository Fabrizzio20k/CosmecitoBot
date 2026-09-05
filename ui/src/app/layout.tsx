import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { ThemeProvider } from "next-themes";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

export const metadata: Metadata = {
  title: "CosmecitoBot · Biblioteca",
  description: "Administración de documentos para el RAG de CosmecitoBot.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es" className="font-sans">
      <body className="min-h-full flex flex-col">
        <ThemeProvider attribute="class" defaultTheme="dark" forcedTheme="dark" enableSystem={false}>
          <TooltipProvider>{children}<Toaster richColors position="top-right" /></TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
