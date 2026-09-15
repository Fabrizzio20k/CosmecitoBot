"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

type Attachment = { id: string; filename: string; byte_size: number };
type SchedulePlan = { scheduled_for: string; recurrence: "none" | "daily" | "weekly" | "monthly"; summary: string };
type Delivery = { channel_id: number; scheduled_for: string; status: string; error: string | null };
type Recipient = { user_id: number; status: string };
type Reminder = {
  id: string; content: string; scheduled_for: string; target_role_id: number | null; status: string;
  recurrence: string; recipients: Recipient[]; attachments: Attachment[];
};
type Announcement = {
  id: string; content: string; created_at: string; status: string; recurrence: string;
  channels: Delivery[]; reminders: Reminder[]; attachments: Attachment[];
};

const api = "/api";
const recurrenceLabel: Record<string, string> = { none: "Una vez", daily: "Diario", weekly: "Semanal", monthly: "Mensual" };

function parseIds(value: string): number[] {
  const ids = [...new Set(value.split(/[,\s]+/).filter(Boolean).map(Number))];
  if (!ids.length || ids.some((id) => !Number.isSafeInteger(id) || id <= 0)) throw new Error("Indica IDs numéricos válidos separados por coma.");
  return ids;
}

function formatDate(value: string) {
  return new Date(value).toLocaleString("es-PE", { timeZone: "America/Lima", dateStyle: "full", timeStyle: "short" });
}

function AttachmentList({ attachments }: { attachments: Attachment[] }) {
  if (!attachments.length) return null;
  return <ul className="attachment-list">{attachments.map((file) => <li key={file.id}>📎 {file.filename} <span>{(file.byte_size / 1024 / 1024).toFixed(1)} MB</span></li>)}</ul>;
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
  const [message, setMessage] = useState("Cargando anuncios…");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void loadAnnouncements();
    // This initial load deliberately runs once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function request(path: string, init: RequestInit = {}) {
    const isForm = init.body instanceof FormData;
    const response = await fetch(`${api}${path}`, {
      ...init,
      cache: "no-store",
      headers: { ...(isForm ? {} : { "Content-Type": "application/json" }), ...(init.headers ?? {}) },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({ detail: "Error inesperado" }));
      throw new Error(body.detail ?? "Error inesperado");
    }
    return response;
  }

  async function loadAnnouncements() {
    try {
      setBusy(true);
      const [announcementResponse, reminderResponse] = await Promise.all([request("/announcements"), request("/reminders")]);
      const loadedAnnouncements = await announcementResponse.json() as Announcement[];
      const loadedReminders = await reminderResponse.json() as Reminder[];
      setAnnouncements(loadedAnnouncements); setReminders(loadedReminders);
      setMessage(loadedAnnouncements.length || loadedReminders.length ? "" : "Aún no hay anuncios ni recordatorios.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "No se pudieron cargar los anuncios."); }
    finally { setBusy(false); }
  }

  async function interpret(instruction: string, setPlan: (plan: SchedulePlan | null) => void) {
    if (!instruction.trim()) throw new Error("Describe cuándo debe enviarse el mensaje.");
    setBusy(true);
    try {
      const response = await request("/schedules/parse", { method: "POST", body: JSON.stringify({ instruction }) });
      const plan = await response.json() as SchedulePlan;
      setPlan(plan); setMessage(`Programación confirmada: ${plan.summary}`);
    } finally { setBusy(false); }
  }

  async function createAnnouncement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      if (announcementWhen.trim() && !announcementPlan) throw new Error("Interpreta y confirma primero la fecha del anuncio.");
      const form = new FormData();
      form.set("content", content.trim()); form.set("channel_ids", JSON.stringify(parseIds(channels)));
      if (announcementPlan) { form.set("scheduled_for", announcementPlan.scheduled_for); form.set("recurrence", announcementPlan.recurrence); }
      announcementFiles.forEach((file) => form.append("files", file));
      setBusy(true); await request("/announcements/upload", { method: "POST", body: form });
      setContent(""); setChannels(""); setAnnouncementWhen(""); setAnnouncementPlan(null); setAnnouncementFiles([]);
      setMessage("Anuncio guardado y en cola de publicación."); await loadAnnouncements();
    } catch (error) { setMessage(error instanceof Error ? error.message : "No se pudo crear el anuncio."); }
    finally { setBusy(false); }
  }

  async function createReminder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      if (!reminderPlan) throw new Error("Interpreta y confirma primero la fecha del recordatorio.");
      const userIds = users.trim() ? parseIds(users) : [];
      const roleId = role.trim() ? Number(role) : undefined;
      if (!userIds.length && !roleId) throw new Error("Indica usuarios, un rol, o ambos.");
      if (roleId !== undefined && (!Number.isSafeInteger(roleId) || roleId <= 0)) throw new Error("El ID de rol no es válido.");
      const form = new FormData();
      form.set("content", reminderContent.trim()); form.set("scheduled_for", reminderPlan.scheduled_for); form.set("recurrence", reminderPlan.recurrence); form.set("user_ids", JSON.stringify(userIds));
      if (roleId) form.set("role_id", String(roleId));
      reminderFiles.forEach((file) => form.append("files", file));
      setBusy(true); await request("/reminders/upload", { method: "POST", body: form });
      setReminderContent(""); setReminderWhen(""); setReminderPlan(null); setReminderFiles([]); setUsers(""); setRole("");
      setMessage("Recordatorio guardado. El bot enviará el DM al llegar la fecha."); await loadAnnouncements();
    } catch (error) { setMessage(error instanceof Error ? error.message : "No se pudo programar el recordatorio."); }
    finally { setBusy(false); }
  }

  async function cancel(path: string, label: string) {
    try { setBusy(true); await request(path, { method: "DELETE" }); setMessage(`${label} cancelado.`); await loadAnnouncements(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "No se pudo cancelar."); } finally { setBusy(false); }
  }

  return <main className="announcement-page">
    <header className="announcement-header"><div><Link href="/" className="back-link">← Biblioteca RAG</Link><h1>Anuncios y recordatorios</h1><p>Describe cuándo enviarlo; el modelo propone fecha, hora y repetición para que la confirmes.</p></div><button type="button" onClick={() => void loadAnnouncements()} disabled={busy}>Actualizar</button></header>
    <section className="announcement-grid">
      <form className="announcement-card" onSubmit={(event) => void createAnnouncement(event)}>
        <h2>Nuevo anuncio</h2>
        <label>Mensaje<textarea value={content} onChange={(event) => setContent(event.target.value)} maxLength={2000} required /></label>
        <label>Canales (IDs separados por coma)<input value={channels} onChange={(event) => setChannels(event.target.value)} required /></label>
        <label>¿Cuándo?<textarea className="schedule-input" value={announcementWhen} onChange={(event) => { setAnnouncementWhen(event.target.value); setAnnouncementPlan(null); }} placeholder="Ej.: el próximo lunes a las 9:30, repetir cada semana" /></label>
        <div className="schedule-actions"><button type="button" disabled={busy || !announcementWhen.trim()} onClick={() => void interpret(announcementWhen, setAnnouncementPlan).catch((error: Error) => setMessage(error.message))}>Interpretar fecha</button>{announcementPlan && <strong className="schedule-preview">✓ {announcementPlan.summary}</strong>}</div>
        <label className="file-input">Adjuntos opcionales (máx. 10; 8 MB c/u, 20 MB total)<input type="file" multiple onChange={(event) => setAnnouncementFiles(Array.from(event.target.files ?? []))} /></label>
        {announcementFiles.length > 0 && <p className="selected-files">📎 {announcementFiles.map((file) => file.name).join(", ")}</p>}
        <button className="save-button" type="submit" disabled={busy}>Guardar anuncio{announcementPlan ? " programado" : " y publicar ahora"}</button>
      </form>
      <form className="announcement-card" onSubmit={(event) => void createReminder(event)}>
        <h2>Nuevo recordatorio privado</h2>
        <label>Mensaje<textarea value={reminderContent} onChange={(event) => setReminderContent(event.target.value)} maxLength={2000} required /></label>
        <label>¿Cuándo?<textarea className="schedule-input" value={reminderWhen} onChange={(event) => { setReminderWhen(event.target.value); setReminderPlan(null); }} placeholder="Ej.: mañana a las 18:00; todos los días" required /></label>
        <div className="schedule-actions"><button type="button" disabled={busy || !reminderWhen.trim()} onClick={() => void interpret(reminderWhen, setReminderPlan).catch((error: Error) => setMessage(error.message))}>Interpretar fecha</button>{reminderPlan && <strong className="schedule-preview">✓ {reminderPlan.summary}</strong>}</div>
        <label>Usuarios (IDs opcionales)<input value={users} onChange={(event) => setUsers(event.target.value)} /></label><label>Rol (ID opcional)<input value={role} onChange={(event) => setRole(event.target.value)} /></label>
        <label className="file-input">Adjuntos opcionales<input type="file" multiple onChange={(event) => setReminderFiles(Array.from(event.target.files ?? []))} /></label>
        {reminderFiles.length > 0 && <p className="selected-files">📎 {reminderFiles.map((file) => file.name).join(", ")}</p>}
        <button className="save-button" type="submit" disabled={busy}>Programar recordatorio</button>
      </form>
    </section>
    {message && <p className="announcement-message">{message}</p>}
    <section className="announcement-list" aria-label="Anuncios registrados">
      {reminders.length > 0 && <article className="announcement-item"><h2>Recordatorios independientes</h2>{reminders.map((reminder) => <div className="reminder" key={reminder.id}><div className="announcement-item-head"><strong>{reminder.status} · {formatDate(reminder.scheduled_for)} · {recurrenceLabel[reminder.recurrence]}</strong>{reminder.status === "scheduled" && <button className="delete-button" type="button" disabled={busy} onClick={() => void cancel(`/reminders/${reminder.id}`, "Recordatorio")}>Cancelar</button>}</div><p>{reminder.content}</p><AttachmentList attachments={reminder.attachments} /><small>{reminder.target_role_id ? `Rol ${reminder.target_role_id}` : ""} {reminder.recipients.map((recipient) => ` · ${recipient.user_id}: ${recipient.status}`).join("")}</small></div>)}</article>}
      {announcements.map((announcement) => <article className="announcement-item" key={announcement.id}><div className="announcement-item-head"><div><span className={`status status-${announcement.status}`}>{announcement.status}</span><time>Creado: {formatDate(announcement.created_at)}</time></div>{announcement.status !== "cancelled" && <button className="delete-button" type="button" disabled={busy} onClick={() => void cancel(`/announcements/${announcement.id}`, "Anuncio")}>Cancelar</button>}</div><p>{announcement.content}</p><AttachmentList attachments={announcement.attachments} /><code>{announcement.id}</code><h3>Entregas · {recurrenceLabel[announcement.recurrence]}</h3><ul>{announcement.channels.map((channel) => <li key={channel.channel_id}>Canal #{channel.channel_id} · <b>{channel.status}</b> · {formatDate(channel.scheduled_for)}{channel.error ? ` · ${channel.error}` : ""}</li>)}</ul>{announcement.reminders.length > 0 && <><h3>Recordatorios</h3>{announcement.reminders.map((reminder) => <div className="reminder" key={reminder.id}><strong>{reminder.status} · {formatDate(reminder.scheduled_for)} · {recurrenceLabel[reminder.recurrence]}</strong><p>{reminder.content}</p><AttachmentList attachments={reminder.attachments} /></div>)}</>}</article>)}
    </section>
  </main>;
}
