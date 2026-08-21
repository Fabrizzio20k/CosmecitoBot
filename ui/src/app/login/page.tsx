"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export default function LoginPage() {
  return (
    <Suspense fallback={<main className="login-page" />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const response = await fetch("/auth/login", {
        body: JSON.stringify({ username, password }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({ detail: "No se pudo iniciar sesión." }));
        throw new Error(body.detail ?? "No se pudo iniciar sesión.");
      }
      const next = searchParams.get("next");
      router.replace(next?.startsWith("/") && !next.startsWith("//") ? next : "/");
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "No se pudo iniciar sesión.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="brand login-brand"><span className="brand-mark">C</span><div><strong>CosmecitoBot</strong><small>Administración</small></div></div>
        <h1>Inicia sesión</h1>
        <p>Accede a la biblioteca de conocimiento del bot.</p>
        <label>Usuario<input autoComplete="username" autoFocus value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
        <label>Contraseña<input autoComplete="current-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
        {error && <p className="login-error" role="alert">{error}</p>}
        <button className="login-button" disabled={submitting} type="submit">{submitting ? "Verificando…" : "Entrar"}</button>
      </form>
    </main>
  );
}
