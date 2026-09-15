"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, LockKeyhole, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export default function LoginPage() { return <Suspense fallback={<main className="min-h-svh" />}><LoginForm /></Suspense>; }

function LoginForm() {
  const router = useRouter(); const searchParams = useSearchParams(); const [username, setUsername] = useState(""); const [password, setPassword] = useState(""); const [error, setError] = useState(""); const [submitting, setSubmitting] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setSubmitting(true); setError(""); try { const response = await fetch("/auth/login", { body: JSON.stringify({ username, password }), headers: { "Content-Type": "application/json" }, method: "POST" }); if (!response.ok) { const body = await response.json().catch(() => ({ detail: "No se pudo iniciar sesión." })); throw new Error(body.detail ?? "No se pudo iniciar sesión."); } const next = searchParams.get("next"); router.replace(next?.startsWith("/") && !next.startsWith("//") ? next : "/"); router.refresh(); } catch (cause) { setError(cause instanceof Error ? cause.message : "No se pudo iniciar sesión."); } finally { setSubmitting(false); } }
  return <main className="grid min-h-svh place-items-center p-5"><Card className="w-full max-w-md border-border/80 bg-card/90 shadow-2xl shadow-black/25"><CardHeader className="gap-4"><div className="flex items-center gap-3"><span className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground"><Sparkles className="size-4" /></span><div><p className="text-sm font-semibold tracking-tight">CosmecitoBot</p><p className="text-xs text-muted-foreground">Centro de operaciones</p></div></div><div><CardTitle className="text-2xl tracking-tight">Bienvenido de vuelta</CardTitle><CardDescription className="mt-2">Accede a tu biblioteca y a las comunicaciones del bot.</CardDescription></div></CardHeader><CardContent><form className="grid gap-4" onSubmit={submit}><label className="grid gap-2 text-sm font-medium">Usuario<Input autoComplete="username" autoFocus value={username} onChange={(event) => setUsername(event.target.value)} required /></label><label className="grid gap-2 text-sm font-medium">Contraseña<Input autoComplete="current-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>{error && <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</p>}<Button className="mt-2" size="lg" disabled={submitting} type="submit"><LockKeyhole />{submitting ? "Verificando…" : "Entrar"}<ArrowRight /></Button></form></CardContent></Card></main>;
}
