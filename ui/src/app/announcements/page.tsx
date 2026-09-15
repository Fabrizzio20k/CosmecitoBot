"use client";

import { FormEvent, useEffect, useState } from "react";
import { BellRing, CalendarClock, CheckCircle2, FileUp, Megaphone, RefreshCw, Send, Trash2 } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

type Attachment = { id: string; filename: string; byte_size: number };
type SchedulePlan = { scheduled_for: string; recurrence: "once" | "daily" | "weekly" | "monthly"; recurrence_weekdays: number[]; recurrence_until: string | null; summary: string };
type Delivery = { channel_id: number; scheduled_for: string; status: string; error: string | null };
type Recipient = { user_id: number; status: string };
type Reminder = { id: string; content: string; scheduled_for: string; target_role_id: number | null; status: string; recurrence: string; recipients: Recipient[]; attachments: Attachment[] };
type Announcement = { id: string; content: string; created_at: string; status: string; recurrence: string; recurrence_until: string | null; channels: Delivery[]; reminders: Reminder[]; attachments: Attachment[] };
type Processing = "loading" | "interpreting" | "saving" | null;

const api = "/api";
const recurrenceLabel: Record<string, string> = { once: "Una vez", daily: "Diario", weekly: "Semanal", monthly: "Mensual" };
const processingLabel: Record<Exclude<Processing, null>, string> = { loading: "Actualizando actividad…", interpreting: "Validando la programación…", saving: "Guardando y preparando entregas…" };
const scheduleFormula = "Fórmulas: 18/09/2026 a las 18:00 · mañana a las 18:00 · todos los lunes, miércoles y viernes desde el 18/09/2026 a las 6pm hasta el 30/11/2026.";

function parseIds(value: string): number[] {
  const ids = [...new Set(value.split(/[,\s]+/).filter(Boolean).map(Number))];
  if (!ids.length || ids.some((id) => !Number.isSafeInteger(id) || id <= 0)) throw new Error("Indica IDs numéricos válidos separados por coma.");
  return ids;
}

function formatDate(value: string) {
  return new Date(value).toLocaleString("es-PE", { timeZone: "America/Lima", dateStyle: "medium", timeStyle: "short" });
}

function StatusBadge({ status }: { status: string }) {
  const variant = status === "completed" || status === "sent" ? "secondary" : status === "failed" || status === "cancelled" ? "destructive" : "outline";
  return <Badge variant={variant}>{status}</Badge>;
}

function Attachments({ files }: { files: Attachment[] }) {
  if (!files.length) return null;
  return <div className="flex flex-wrap gap-2">{files.map((file) => <Badge key={file.id} variant="secondary" className="max-w-full truncate">📎 {file.filename}</Badge>)}</div>;
}

export default function AnnouncementsPage() {
  const [announcements, setAnnouncements] = useState<Announcement[]>([]);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [content, setContent] = useState("");
  const [channels, setChannels] = useState("");
  const [announcementWhen, setAnnouncementWhen] = useState("");
  const [announcementPlan, setAnnouncementPlan] = useState<SchedulePlan | null>(null);
  const [announcementFiles, setAnnouncementFiles] = useState<File[]>([]);
  const [reminderContent, setReminderContent] = useState("");
  const [reminderWhen, setReminderWhen] = useState("");
  const [reminderPlan, setReminderPlan] = useState<SchedulePlan | null>(null);
  const [reminderFiles, setReminderFiles] = useState<File[]>([]);
  const [users, setUsers] = useState("");
  const [role, setRole] = useState("");
  const [message, setMessage] = useState("Cargando actividad…");
  const [processing, setProcessing] = useState<Processing>("loading");

  useEffect(() => {
    void loadAnnouncements();
    // This initial load deliberately runs once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const busy = processing !== null;

  async function request(path: string, init: RequestInit = {}) {
    const isForm = init.body instanceof FormData;
    const response = await fetch(`${api}${path}`, { ...init, cache: "no-store", headers: { ...(isForm ? {} : { "Content-Type": "application/json" }), ...(init.headers ?? {}) } });
    if (!response.ok) {
      const body = await response.json().catch(() => ({ detail: "Error inesperado" }));
      throw new Error(body.detail ?? "Error inesperado");
    }
    return response;
  }

  async function loadAnnouncements() {
    try {
      setProcessing("loading");
      const [announcementResponse, reminderResponse] = await Promise.all([request("/announcements"), request("/reminders")]);
      const loadedAnnouncements = await announcementResponse.json() as Announcement[];
      const loadedReminders = await reminderResponse.json() as Reminder[];
      setAnnouncements(loadedAnnouncements); setReminders(loadedReminders);
      setMessage(loadedAnnouncements.length || loadedReminders.length ? "Actividad actualizada." : "Aún no hay mensajes programados.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "No se pudo cargar la actividad."); }
    finally { setProcessing(null); }
  }

  async function interpret(instruction: string, setPlan: (plan: SchedulePlan | null) => void) {
    if (!instruction.trim()) { setMessage("Describe cuándo debe enviarse el mensaje."); return; }
    try {
      setProcessing("interpreting");
      const response = await request("/schedules/parse", { method: "POST", body: JSON.stringify({ instruction }) });
      const plan = await response.json() as SchedulePlan;
      setPlan(plan); setMessage("Interpretación lista. Revísala antes de guardar.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "No se pudo interpretar la fecha."); }
    finally { setProcessing(null); }
  }

  async function createAnnouncement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      if (announcementWhen.trim() && !announcementPlan) throw new Error("Primero interpreta la fecha y revisa la propuesta.");
      const form = new FormData();
      form.set("content", content.trim()); form.set("channel_ids", JSON.stringify(parseIds(channels)));
      if (announcementPlan) { form.set("scheduled_for", announcementPlan.scheduled_for); form.set("recurrence", announcementPlan.recurrence); form.set("recurrence_weekdays", JSON.stringify(announcementPlan.recurrence_weekdays)); if (announcementPlan.recurrence_until) form.set("recurrence_until", announcementPlan.recurrence_until); }
      announcementFiles.forEach((file) => form.append("files", file));
      setProcessing("saving"); await request("/announcements/upload", { method: "POST", body: form });
      setContent(""); setChannels(""); setAnnouncementWhen(""); setAnnouncementPlan(null); setAnnouncementFiles([]);
      setMessage("Anuncio guardado y en cola."); await loadAnnouncements();
    } catch (error) { setMessage(error instanceof Error ? error.message : "No se pudo crear el anuncio."); }
    finally { setProcessing(null); }
  }

  async function createReminder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      if (!reminderPlan) throw new Error("Primero interpreta la fecha y revisa la propuesta.");
      const userIds = users.trim() ? parseIds(users) : [];
      const roleId = role.trim() ? Number(role) : undefined;
      if (!userIds.length && !roleId) throw new Error("Indica usuarios, un rol, o ambos.");
      if (roleId !== undefined && (!Number.isSafeInteger(roleId) || roleId <= 0)) throw new Error("El ID de rol no es válido.");
      const form = new FormData();
      form.set("content", reminderContent.trim()); form.set("scheduled_for", reminderPlan.scheduled_for); form.set("recurrence", reminderPlan.recurrence); form.set("recurrence_weekdays", JSON.stringify(reminderPlan.recurrence_weekdays)); form.set("user_ids", JSON.stringify(userIds)); if (reminderPlan.recurrence_until) form.set("recurrence_until", reminderPlan.recurrence_until);
      if (roleId) form.set("role_id", String(roleId));
      reminderFiles.forEach((file) => form.append("files", file));
      setProcessing("saving"); await request("/reminders/upload", { method: "POST", body: form });
      setReminderContent(""); setReminderWhen(""); setReminderPlan(null); setReminderFiles([]); setUsers(""); setRole("");
      setMessage("Recordatorio guardado y en cola."); await loadAnnouncements();
    } catch (error) { setMessage(error instanceof Error ? error.message : "No se pudo programar el recordatorio."); }
    finally { setProcessing(null); }
  }

  async function cancel(path: string, label: string) {
    try { setProcessing("saving"); await request(path, { method: "DELETE" }); setMessage(`${label} cancelado.`); await loadAnnouncements(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "No se pudo cancelar."); } finally { setProcessing(null); }
  }

  return <AppShell title="Mensajes" description="Anuncios, recordatorios y programación inteligente" actions={<Button variant="outline" size="sm" onClick={() => void loadAnnouncements()} disabled={busy}><RefreshCw className={busy ? "animate-spin" : ""} />Actualizar</Button>}>
    <div className="mx-auto grid max-w-7xl gap-5">
      <section className="rounded-2xl border border-primary/25 bg-primary/10 px-4 py-3 shadow-sm sm:px-5" aria-live="polite">
        <div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-xl bg-primary text-primary-foreground"><CalendarClock className={busy ? "size-4 animate-pulse" : "size-4"} /></span><div className="min-w-0"><p className="text-sm font-semibold">{processing ? processingLabel[processing] : message}</p><p className="text-xs text-muted-foreground">La fecha siempre se confirma en hora Lima antes de enviarla.</p></div></div>
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <Card className="border-border/80 bg-card/85 shadow-xl shadow-black/10"><CardHeader><div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-xl bg-primary/15 text-primary"><Megaphone className="size-4" /></span><div><CardTitle className="text-base">Nuevo anuncio</CardTitle><CardDescription>Publica ahora o programa una entrega para tus canales.</CardDescription></div></div></CardHeader><Separator /><CardContent className="pt-5"><form className="grid gap-4" onSubmit={(event) => void createAnnouncement(event)}>
          <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">Mensaje<Textarea value={content} onChange={(event) => setContent(event.target.value)} maxLength={2000} required className="min-h-28 bg-background/50" /></label>
          <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">Canales<Textarea value={channels} onChange={(event) => setChannels(event.target.value)} placeholder="IDs separados por coma" required className="min-h-18 bg-background/50" /></label>
          <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">¿Cuándo?<Textarea value={announcementWhen} onChange={(event) => { setAnnouncementWhen(event.target.value); setAnnouncementPlan(null); }} placeholder="Ej.: todos los viernes desde el 18 de setiembre a las 6pm" className="min-h-20 bg-background/50" /></label>
          <p className="rounded-xl border border-primary/25 bg-primary/10 px-3 py-2 text-xs leading-5 text-primary">{scheduleFormula}</p>
          <div className="flex flex-wrap items-center gap-2"><Button type="button" variant="secondary" size="sm" disabled={busy || !announcementWhen.trim()} onClick={() => void interpret(announcementWhen, setAnnouncementPlan)}>Validar fecha</Button>{announcementPlan && <Badge className="h-auto whitespace-normal bg-primary/15 py-1.5 text-left text-primary hover:bg-primary/15"><CheckCircle2 />{announcementPlan.summary}</Badge>}</div>
          <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-dashed border-border bg-muted/25 px-3 py-2.5 text-sm text-muted-foreground hover:bg-muted/50"><FileUp className="size-4" /><span className="truncate">{announcementFiles.length ? announcementFiles.map((file) => file.name).join(", ") : "Adjuntar archivos (opcional)"}</span><input className="sr-only" type="file" multiple onChange={(event) => setAnnouncementFiles(Array.from(event.target.files ?? []))} /></label>
          <Button type="submit" disabled={busy}><Send />{announcementPlan ? "Confirmar y programar" : "Publicar ahora"}</Button>
        </form></CardContent></Card>

        <Card className="border-border/80 bg-card/85 shadow-xl shadow-black/10"><CardHeader><div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-xl bg-primary/15 text-primary"><BellRing className="size-4" /></span><div><CardTitle className="text-base">Nuevo recordatorio</CardTitle><CardDescription>Envía un DM a usuarios o a los miembros de un rol.</CardDescription></div></div></CardHeader><Separator /><CardContent className="pt-5"><form className="grid gap-4" onSubmit={(event) => void createReminder(event)}>
          <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">Mensaje<Textarea value={reminderContent} onChange={(event) => setReminderContent(event.target.value)} maxLength={2000} required className="min-h-28 bg-background/50" /></label>
          <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">¿Cuándo?<Textarea value={reminderWhen} onChange={(event) => { setReminderWhen(event.target.value); setReminderPlan(null); }} placeholder="Ej.: todos los viernes desde el 18 de setiembre a las 6pm hasta el 30 de noviembre" required className="min-h-20 bg-background/50" /></label>
          <p className="rounded-xl border border-primary/25 bg-primary/10 px-3 py-2 text-xs leading-5 text-primary">{scheduleFormula}</p>
          <div className="flex flex-wrap items-center gap-2"><Button type="button" variant="secondary" size="sm" disabled={busy || !reminderWhen.trim()} onClick={() => void interpret(reminderWhen, setReminderPlan)}>Validar fecha</Button>{reminderPlan && <Badge className="h-auto whitespace-normal bg-primary/15 py-1.5 text-left text-primary hover:bg-primary/15"><CheckCircle2 />{reminderPlan.summary}</Badge>}</div>
          <div className="grid gap-3 sm:grid-cols-2"><label className="grid gap-1.5 text-xs font-medium text-muted-foreground">Usuarios<Input value={users} onChange={(event) => setUsers(event.target.value)} placeholder="IDs separados por coma" /></label><label className="grid gap-1.5 text-xs font-medium text-muted-foreground">Rol<Input value={role} onChange={(event) => setRole(event.target.value)} placeholder="ID opcional" /></label></div>
          <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-dashed border-border bg-muted/25 px-3 py-2.5 text-sm text-muted-foreground hover:bg-muted/50"><FileUp className="size-4" /><span className="truncate">{reminderFiles.length ? reminderFiles.map((file) => file.name).join(", ") : "Adjuntar archivos (opcional)"}</span><input className="sr-only" type="file" multiple onChange={(event) => setReminderFiles(Array.from(event.target.files ?? []))} /></label>
          <Button type="submit" disabled={busy}><Send />Confirmar y programar</Button>
        </form></CardContent></Card>
      </section>

      <Card className="border-border/80 bg-card/85 shadow-xl shadow-black/10"><CardHeader className="flex-row items-center justify-between gap-3"><div><CardTitle className="text-base">Actividad</CardTitle><CardDescription>Entregas próximas, enviadas o con incidencias.</CardDescription></div><Badge variant="secondary">{announcements.length + reminders.length} registros</Badge></CardHeader><Separator /><CardContent className="grid gap-3 pt-5">
        {processing === "loading" && !announcements.length && !reminders.length ? Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-24 w-full" />) : !announcements.length && !reminders.length ? <div className="grid min-h-40 place-items-center text-center text-sm text-muted-foreground">Todavía no hay entregas. Crea un anuncio o recordatorio arriba.</div> : <>
          {reminders.map((reminder) => <article key={reminder.id} className="grid gap-3 rounded-xl border border-border/70 bg-background/35 p-4 sm:grid-cols-[minmax(0,1fr)_auto]"><div className="grid min-w-0 gap-2"><div className="flex flex-wrap items-center gap-2"><StatusBadge status={reminder.status} /><span className="text-xs text-muted-foreground">{formatDate(reminder.scheduled_for)} · {recurrenceLabel[reminder.recurrence]}</span></div><p className="whitespace-pre-wrap text-sm leading-6">{reminder.content}</p><Attachments files={reminder.attachments} /></div>{reminder.status === "scheduled" && <Button variant="ghost" size="sm" className="text-destructive hover:bg-destructive/10 hover:text-destructive" onClick={() => void cancel(`/reminders/${reminder.id}`, "Recordatorio")} disabled={busy}><Trash2 />Cancelar</Button>}</article>)}
          {announcements.map((announcement) => <article key={announcement.id} className="grid gap-3 rounded-xl border border-border/70 bg-background/35 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div className="flex flex-wrap items-center gap-2"><StatusBadge status={announcement.status} /><span className="text-xs text-muted-foreground">{recurrenceLabel[announcement.recurrence]} · creado {formatDate(announcement.created_at)}</span></div>{announcement.status !== "cancelled" && <Button variant="ghost" size="sm" className="text-destructive hover:bg-destructive/10 hover:text-destructive" onClick={() => void cancel(`/announcements/${announcement.id}`, "Anuncio")} disabled={busy}><Trash2 />Cancelar</Button>}</div><p className="whitespace-pre-wrap text-sm leading-6">{announcement.content}</p><Attachments files={announcement.attachments} /><div className="grid gap-1 text-xs text-muted-foreground">{announcement.channels.map((channel) => <span key={channel.channel_id}>Canal #{channel.channel_id} · {channel.status} · {formatDate(channel.scheduled_for)}{channel.error ? ` · ${channel.error}` : ""}</span>)}</div></article>)}
        </>}
      </CardContent></Card>
    </div>
  </AppShell>;
}
