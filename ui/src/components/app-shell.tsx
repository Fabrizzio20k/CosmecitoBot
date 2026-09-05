"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { BookOpenText, CalendarClock, ChevronRight, LogOut, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
} from "@/components/ui/sidebar";

type AppShellProps = {
  children: ReactNode;
  title: string;
  description: string;
  actions?: ReactNode;
};

const navigation = [
  { href: "/", label: "Biblioteca", detail: "Conocimiento RAG", icon: BookOpenText },
  { href: "/announcements", label: "Mensajes", detail: "Anuncios y recordatorios", icon: CalendarClock },
];

export function AppShell({ children, title, description, actions }: AppShellProps) {
  const pathname = usePathname();
  const router = useRouter();

  async function logout() {
    await fetch("/auth/logout", { method: "POST" });
    router.replace("/login");
    router.refresh();
  }

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon" variant="inset">
        <SidebarHeader className="p-3">
          <Link href="/" className="group flex items-center gap-3 rounded-xl px-2 py-2 outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring">
            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-sidebar-primary text-sidebar-primary-foreground shadow-sm">
              <Sparkles className="size-4" />
            </span>
            <span className="grid min-w-0 gap-0.5 group-data-[collapsible=icon]:hidden">
              <strong className="truncate text-sm font-semibold tracking-tight">CosmecitoBot</strong>
              <span className="text-xs text-sidebar-foreground/60">Centro de operaciones</span>
            </span>
          </Link>
        </SidebarHeader>

        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Espacio de trabajo</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {navigation.map((item) => {
                  const Icon = item.icon;
                  const active = pathname === item.href;
                  return (
                    <SidebarMenuItem key={item.href}>
                      <SidebarMenuButton render={<Link href={item.href} />} isActive={active} tooltip={item.label}>
                        <Icon />
                        <span>{item.label}</span>
                        {active && <ChevronRight className="ml-auto size-3.5" />}
                      </SidebarMenuButton>
                      <p className="px-2 pb-2 text-[11px] leading-none text-sidebar-foreground/50 group-data-[collapsible=icon]:hidden">{item.detail}</p>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>

        <SidebarFooter className="p-3">
          <div className="rounded-xl border border-sidebar-border bg-sidebar-accent/40 p-3 group-data-[collapsible=icon]:hidden">
            <div className="mb-1 flex items-center gap-2 text-xs font-medium"><span className="size-2 rounded-full bg-emerald-400" />Servicios listos</div>
            <p className="text-[11px] leading-relaxed text-sidebar-foreground/60">Tu contenido se procesa de forma privada.</p>
          </div>
          <Button variant="ghost" className="mt-2 w-full justify-start text-sidebar-foreground/70 hover:text-sidebar-foreground" onClick={() => void logout()}>
            <LogOut /> <span>Salir</span>
          </Button>
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>

      <SidebarInset className="bg-background">
        <header className="sticky top-0 z-20 flex min-h-16 items-center justify-between gap-4 border-b border-border/70 bg-background/85 px-4 backdrop-blur-xl md:px-7">
          <div className="flex min-w-0 items-center gap-3"><SidebarTrigger /><span className="hidden h-5 w-px bg-border sm:block" /><div className="min-w-0"><div className="flex items-center gap-2"><h1 className="truncate text-sm font-semibold tracking-tight">{title}</h1><Badge variant="secondary" className="hidden sm:inline-flex">Lima · UTC−5</Badge></div><p className="hidden truncate text-xs text-muted-foreground sm:block">{description}</p></div></div>
          <div className="flex shrink-0 items-center gap-2">{actions}</div>
        </header>
        <main className="min-h-[calc(100svh-4rem)] p-4 md:p-7">{children}</main>
      </SidebarInset>
    </SidebarProvider>
  );
}
