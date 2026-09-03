"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

type Delivery = {
  channel_id: number;
  scheduled_for: string;
  status: string;
  discord_message_id: number | null;
  error: string | null;
};

type Recipient = {
  user_id: number;
  source: string;
  status: string;
  error: string | null;
};

type Reminder = {
  id: string;
  content: string;
  scheduled_for: string;
  target_role_id: number | null;
  status: string;
  recipients: Recipient[];
};

type Announcement = {
  id: string;
  content: string;
  status: string;
  created_at: string;
  channels: Delivery[];
  reminders: Reminder[];
};

const api = "/api";

function parseIds(value: string) {
  const ids = [...new Set(value.split(/[,\s]+/).filter(Boolean).map(Number))];
  if (!ids.length || ids.some((id) => !Number.isSafeInteger(id) || id <= 0)) {
    throw new Error("Indica IDs numéricos válidos separados por coma.");
  }
  return ids;
}

function localTimeToIso(value: string) {
  if (!value) return undefined;
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) throw new Error("La fecha programada no es válida.");
  return date.toISOString();
}

export default function AnnouncementsPage() {
  const [announcements, setAnnouncements] = useState<Announcement[]>([]);
  const [content, setContent] = useState("");
  const [channels, setChannels] = useState("");
  const [scheduledFor, setScheduledFor] = useState("");
  const [reminderFor, setReminderFor] = useState("");
  const [reminderContent, setReminderContent] = useState("");
  const [reminderDate, setReminderDate] = useState("");
  const [users, setUsers] = useState("");
  const [role, setRole] = useState("");
  const [message, setMessage] = useState("Cargando anuncios…");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void loadAnnouncements();
    // loadAnnouncements is intentionally invoked once when this page mounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function request(path: string, init: RequestInit = {}) {
    const response = await fetch(`${api}${path}`, {
      ...init,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
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
      const response = await request("/announcements");
      const loaded = await response.json() as Announcement[];
      setAnnouncements(loaded);
      setReminderFor((current) => current || loaded[0]?.id || "");
      setMessage(loaded.length ? "" : "Aún no hay anuncios.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudieron cargar los anuncios.");
    } finally {
      setBusy(false);
    }
  }

  async function createAnnouncement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      setBusy(true);
      await request("/announcements", {
        method: "POST",
        body: JSON.stringify({ content: content.trim(), channel_ids: parseIds(channels), scheduled_for: localTimeToIso(scheduledFor) }),
      });
      setContent(""); setChannels(""); setScheduledFor("");
      setMessage("Anuncio guardado y en cola de publicación.");
      await loadAnnouncements();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo crear el anuncio.");
    } finally {
      setBusy(false);
    }
  }

  async function createReminder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      if (!reminderFor) throw new Error("Selecciona el anuncio que se recordará.");
      if (!reminderDate) throw new Error("Indica la fecha y hora del recordatorio.");
      const userIds = users.trim() ? parseIds(users) : [];
      const roleId = role.trim() ? Number(role.trim()) : undefined;
      if (!userIds.length && !roleId) throw new Error("Indica usuarios, un rol, o ambos.");
      if (roleId !== undefined && (!Number.isSafeInteger(roleId) || roleId <= 0)) throw new Error("El ID de rol no es válido.");
      setBusy(true);
      await request(`/announcements/${reminderFor}/reminders`, {
        method: "POST",
        body: JSON.stringify({
          content: reminderContent.trim(),
          scheduled_for: localTimeToIso(reminderDate),
          user_ids: userIds,
          role_id: roleId,
        }),
      });
      setReminderContent(""); setReminderDate(""); setUsers(""); setRole("");
      setMessage("Recordatorio guardado. El bot enviará DM al llegar la fecha.");
      await loadAnnouncements();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo programar el recordatorio.");
    } finally {
      setBusy(false);
    }
  }

  async function cancelAnnouncement(id: string) {
    if (!window.confirm("¿Cancelar este anuncio y todos sus recordatorios pendientes?")) return;
    try {
      setBusy(true);
      await request(`/announcements/${id}`, { method: "DELETE" });
      setMessage("Anuncio cancelado.");
      await loadAnnouncements();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo cancelar el anuncio.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="announcement-page">
      <header className="announcement-header">
        <div><Link href="/" className="back-link">← Biblioteca RAG</Link><h1>Anuncios y recordatorios</h1><p>Los anuncios se publican en canales; los recordatorios se envían por DM.</p></div>
        <button type="button" onClick={() => void loadAnnouncements()} disabled={busy}>Actualizar</button>
      </header>

      <section className="announcement-grid">
        <form className="announcement-card" onSubmit={(event) => void createAnnouncement(event)}>
          <h2>Nuevo anuncio global</h2>
          <label>Mensaje<textarea value={content} onChange={(event) => setContent(event.target.value)} maxLength={2000} required /></label>
          <label>IDs de canales, separados por coma<input value={channels} onChange={(event) => setChannels(event.target.value)} placeholder="123..., 456..." required /></label>
          <label>Publicar en fecha/hora (opcional)<input type="datetime-local" value={scheduledFor} onChange={(event) => setScheduledFor(event.target.value)} /></label>
          <button className="save-button" type="submit" disabled={busy}>Guardar anuncio</button>
        </form>

        <form className="announcement-card" onSubmit={(event) => void createReminder(event)}>
          <h2>Nuevo recordatorio privado</h2>
          <label>Anuncio<select value={reminderFor} onChange={(event) => setReminderFor(event.target.value)} required><option value="">Selecciona un anuncio</option>{announcements.filter((item) => item.status !== "cancelled").map((item) => <option key={item.id} value={item.id}>{item.content.slice(0, 70)} · {item.id.slice(0, 8)}</option>)}</select></label>
          <label>Mensaje<textarea value={reminderContent} onChange={(event) => setReminderContent(event.target.value)} maxLength={2000} required /></label>
          <label>Enviar en fecha/hora<input type="datetime-local" value={reminderDate} onChange={(event) => setReminderDate(event.target.value)} required /></label>
          <label>IDs de usuarios (opcional, separados por coma)<input value={users} onChange={(event) => setUsers(event.target.value)} placeholder="123..., 456..." /></label>
          <label>ID de rol (opcional)<input value={role} onChange={(event) => setRole(event.target.value)} placeholder="123..." /></label>
          <button className="save-button" type="submit" disabled={busy}>Programar recordatorio</button>
        </form>
      </section>

      {message && <p className="announcement-message">{message}</p>}
      <section className="announcement-list" aria-label="Anuncios registrados">
        {announcements.map((announcement) => (
          <article className="announcement-item" key={announcement.id}>
            <div className="announcement-item-head"><div><span className={`status status-${announcement.status}`}>{announcement.status}</span><time>{new Date(announcement.created_at).toLocaleString()}</time></div>{announcement.status !== "cancelled" && <button className="delete-button" type="button" disabled={busy} onClick={() => void cancelAnnouncement(announcement.id)}>Cancelar</button>}</div>
            <p>{announcement.content}</p><code>{announcement.id}</code>
            <h3>Canales</h3><ul>{announcement.channels.map((channel) => <li key={channel.channel_id}>#{channel.channel_id} · {channel.status} · {new Date(channel.scheduled_for).toLocaleString()}{channel.error ? ` · ${channel.error}` : ""}</li>)}</ul>
            {announcement.reminders.length > 0 && <><h3>Recordatorios</h3>{announcement.reminders.map((reminder) => <div className="reminder" key={reminder.id}><strong>{reminder.status} · {new Date(reminder.scheduled_for).toLocaleString()}</strong><p>{reminder.content}</p><small>{reminder.target_role_id ? `Rol ${reminder.target_role_id}` : ""} {reminder.recipients.map((recipient) => ` · ${recipient.user_id}: ${recipient.status}`).join("")}</small></div>)}</>}
          </article>
        ))}
      </section>
    </main>
  );
}
