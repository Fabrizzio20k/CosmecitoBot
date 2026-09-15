"use client";

import { FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  BellRing,
  CalendarClock,
  Megaphone,
  RefreshCw,
  Send,
  Trash2,
} from "lucide-react";

type Attachment = {
  id: string;
  filename: string;
  content_type: string | null;
  byte_size: number;
};
type SchedulePlan = {
  scheduled_for: string;
  recurrence: "none" | "daily" | "weekly" | "monthly";
  summary: string;
  timezone: string;
};
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
  announcement_id: string | null;
  content: string;
  scheduled_for: string;
  target_role_id: number | null;
  status: string;
  recurrence: string;
  recipients: Recipient[];
  attachments: Attachment[];
};
type Announcement = {
  id: string;
  content: string;
  status: string;
  recurrence: string;
  created_at: string;
  channels: Delivery[];
  reminders: Reminder[];
  attachments: Attachment[];
};

const api = "/api";
const formatDate = (value: string) =>
  new Date(value).toLocaleString("es-PE", {
    timeZone: "America/Lima",
    dateStyle: "full",
    timeStyle: "short",
  });
const formatBytes = (bytes: number) =>
  bytes < 1024 * 1024
    ? `${Math.ceil(bytes / 1024)} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
const recurrenceLabel: Record<string, string> = {
  none: "Una vez",
  daily: "Diario",
  weekly: "Semanal",
  monthly: "Mensual",
};

function parseIds(value: string) {
  const ids = [
    ...new Set(
      value
        .split(/[,\s]+/)
        .filter(Boolean)
        .map(Number),
    ),
  ];
  if (!ids.length || ids.some((id) => !Number.isSafeInteger(id) || id <= 0))
    throw new Error("Indica IDs numéricos válidos separados por coma.");
  return ids;
}

function AttachmentNames({ attachments }: { attachments: Attachment[] }) {
  if (!attachments.length) return null;
  return (
    <ul className="attachment-list">
      {attachments.map((file) => (
        <li key={file.id}>
          📎 {file.filename} <span>{formatBytes(file.byte_size)}</span>
        </li>
      ))}
    </ul>
  );
}

export default function AnnouncementsPage() {
  const [announcements, setAnnouncements] = useState<Announcement[]>([]);
  const [standaloneReminders, setStandaloneReminders] = useState<Reminder[]>(
    [],
  );
  const [content, setContent] = useState("");
  const [channels, setChannels] = useState("");
  const [announcementWhen, setAnnouncementWhen] = useState("");
  const [announcementPlan, setAnnouncementPlan] = useState<SchedulePlan | null>(
    null,
  );
  const [announcementFiles, setAnnouncementFiles] = useState<File[]>([]);
  const [reminderFor, setReminderFor] = useState("");
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
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const scheduledCount = useMemo(
    () =>
      [
        ...standaloneReminders,
        ...announcements.flatMap((item) => item.reminders),
      ].filter((item) => item.status === "scheduled").length,
    [announcements, standaloneReminders],
  );
  async function request(path: string, init: RequestInit = {}) {
    const response = await fetch(`${api}${path}`, {
      ...init,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    });
    if (!response.ok) {
      const body = await response
        .json()
        .catch(() => ({ detail: "Error inesperado" }));
      throw new Error(body.detail ?? "Error inesperado");
    }
    return response;
  }
  async function loadAnnouncements() {
    try {
      setBusy(true);
      const [announcementResponse, reminderResponse] = await Promise.all([
        request("/announcements"),
        request("/reminders"),
      ]);
      setAnnouncements(await announcementResponse.json());
      setStandaloneReminders(await reminderResponse.json());
      try {
        setRoles(await (await request("/discord/roles")).json());
        setRolesError("");
      } catch (error) {
        setRoles([]);
        setRolesError(
          error instanceof Error
            ? error.message
            : "No se pudieron cargar los roles.",
        );
      }
    } catch (error) {
      toast.error("No se pudo cargar la actividad", {
        description:
          error instanceof Error ? error.message : "Inténtalo otra vez.",
      });
    } finally {
      setLoaded(true);
      setBusy(false);
    }
  }
  async function createAnnouncement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      setBusy(true);
      await request("/announcements", {
        method: "POST",
        body: JSON.stringify({
          content: content.trim(),
          channel_ids: parseIds(channels),
          scheduled_for: limaTimeToIso(scheduledFor),
        }),
      });
      setContent("");
      setChannels("");
      setScheduledFor("");
      setAnnouncementOpen(false);
      toast.success("Anuncio puesto en cola");
      await loadAnnouncements();
    } catch (error) {
      toast.error("No se pudo crear el anuncio", {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setBusy(false);
    }
  }
  async function createReminder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      if (!reminderDate)
        throw new Error("Elige la fecha y hora del primer envío.");
      const userIds = users.trim() ? parseIds(users) : [];
      const roleId = role === "none" ? undefined : Number(role);
      const interval = Number(recurrenceInterval);
      if (!userIds.length && !roleId)
        throw new Error("Indica usuarios, un rol, o ambos.");
      if (!Number.isSafeInteger(interval) || interval < 1 || interval > 365)
        throw new Error("El intervalo debe estar entre 1 y 365.");
      setBusy(true);
      await request("/reminders", {
        method: "POST",
        body: JSON.stringify({
          content: reminderContent.trim(),
          scheduled_for: limaTimeToIso(reminderDate),
          user_ids: userIds,
          role_id: roleId,
          announcement_id: reminderFor === "none" ? undefined : reminderFor,
          recurrence,
          recurrence_interval: interval,
          recurrence_weekdays:
            recurrence === "weekly" ? recurrenceWeekdays : [],
          recurrence_until:
            recurrence === "once" ? undefined : limaTimeToIso(recurrenceUntil),
        }),
      });
      setReminderContent("");
      setReminderDate("");
      setUsers("");
      setRole("none");
      setRecurrence("once");
      setRecurrenceInterval("1");
      setRecurrenceWeekdays([]);
      setRecurrenceUntil("");
      setReminderOpen(false);
      toast.success("Recordatorio programado");
      await loadAnnouncements();
    } catch (error) {
      toast.error("No se pudo programar", {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setBusy(false);
    }
  }
  async function cancelAnnouncement(id: string) {
    try {
      setBusy(true);
      await request(`/announcements/${id}`, { method: "DELETE" });
      toast.success("Anuncio cancelado");
      await loadAnnouncements();
    } catch (error) {
      toast.error("No se pudo cancelar", {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setBusy(false);
    }
  }
  async function cancelReminder(reminder: Reminder) {
    try {
      setBusy(true);
      await request(`/reminders/${reminder.id}`, { method: "DELETE" });
      toast.success(
        reminder.recurrence === "once"
          ? "Recordatorio cancelado"
          : "Serie de recordatorios cancelada",
      );
      await loadAnnouncements();
    } catch (error) {
      toast.error("No se pudo cancelar", {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setBusy(false);
    }
  }
  function toggleWeekday(day: number) {
    setRecurrenceWeekdays((current) =>
      current.includes(day)
        ? current.filter((value) => value !== day)
        : [...current, day].sort(),
    );
  }
  function reminderRule(reminder: Reminder) {
    if (reminder.recurrence === "weekly")
      return `Semanal${reminder.recurrence_weekdays.length ? ` · ${reminder.recurrence_weekdays.map((day) => weekdayLabels[day]).join(", ")}` : ""}`;
    return reminder.recurrence === "once"
      ? "Una vez"
      : `${recurrenceLabels[reminder.recurrence]} · cada ${reminder.recurrence_interval}`;
  }
  function CancelButton({
    reminder,
    announcementId,
  }: {
    reminder?: Reminder;
    announcementId?: string;
  }) {
    const text =
      reminder?.recurrence !== "once" ? "Cancelar serie" : "Cancelar";
    const onConfirm = reminder
      ? () => void cancelReminder(reminder)
      : () => void cancelAnnouncement(announcementId!);
    return (
      <AlertDialog>
        <AlertDialogTrigger
          render={
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:bg-destructive/10 hover:text-destructive"
            />
          }
        >
          <Trash2 />
          {text}
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogMedia>
              <Trash2 />
            </AlertDialogMedia>
            <AlertDialogTitle>¿Confirmas la cancelación?</AlertDialogTitle>
            <AlertDialogDescription>
              {reminder?.recurrence !== "once"
                ? "Se detendrán todas las futuras repeticiones de esta serie."
                : "Las entregas pendientes no se enviarán."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Volver</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={onConfirm}>
              Cancelar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );
  }
  function ReminderRow({ reminder }: { reminder: Reminder }) {
    return (
      <div className="group grid min-w-0 gap-2 rounded-xl border border-border/70 bg-background/35 p-4 transition-colors hover:bg-muted/40 md:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={statusVariant(reminder.status)}>
              {reminder.status}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {limaDate(reminder.scheduled_for)} · Lima
            </span>
          </div>
          <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">
            {reminder.content}
          </p>
          <p className="mt-2 break-words text-xs text-muted-foreground">
            {reminderRule(reminder)}
            {reminder.recurrence_until
              ? ` · hasta ${limaDate(reminder.recurrence_until)}`
              : ""}
            {reminder.target_role_id ? ` · Rol ${reminder.target_role_id}` : ""}
            {reminder.recipients.length
              ? ` · ${reminder.recipients.length} destinatarios`
              : ""}
          </p>
        </div>
        {reminder.status === "scheduled" && (
          <div>
            <CancelButton reminder={reminder} />
          </div>
        )}
      </div>
    );
  }
  const actions = (
    <>
      <Button
        variant="outline"
        size="icon-sm"
        onClick={() => void loadAnnouncements()}
        disabled={busy}
        aria-label="Actualizar"
      >
        <RefreshCw className={busy ? "animate-spin" : ""} />
      </Button>
      <Dialog open={announcementOpen} onOpenChange={setAnnouncementOpen}>
        <DialogTrigger
          render={<Button variant="outline" aria-label="Crear anuncio" />}
        >
          <Megaphone />
          <span className="hidden sm:inline">Anuncio</span>
          <span className="sr-only">Crear anuncio</span>
        </DialogTrigger>
        <DialogContent className="w-[calc(100%_-_2rem)] max-w-lg">
          <form
            onSubmit={(event) => void createAnnouncement(event)}
            className="grid gap-4"
          >
            <DialogHeader>
              <DialogTitle>Nuevo anuncio</DialogTitle>
              <DialogDescription>
                Publica ahora o deja listo un mensaje para tus canales.
              </DialogDescription>
            </DialogHeader>
            <label className="grid gap-2 text-sm font-medium">
              Mensaje
              <Textarea
                value={content}
                onChange={(event) => setContent(event.target.value)}
                maxLength={2000}
                required
                className="min-h-28"
              />
            </label>
            <label className="grid gap-2 text-sm font-medium">
              Canales
              <Input
                value={channels}
                onChange={(event) => setChannels(event.target.value)}
                placeholder="123..., 456..."
                required
              />
            </label>
            <label className="grid gap-2 text-sm font-medium">
              Fecha de publicación{" "}
              <span className="font-normal text-muted-foreground">
                opcional
              </span>
              <LimaDateTimePicker
                value={scheduledFor}
                onChange={setScheduledFor}
              />
            </label>
            <DialogFooter>
              <Button
                variant="outline"
                type="button"
                onClick={() => setAnnouncementOpen(false)}
              >
                Cancelar
              </Button>
              <Button type="submit" disabled={busy}>
                <Send />
                Guardar anuncio
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog open={reminderOpen} onOpenChange={setReminderOpen}>
        <DialogTrigger render={<Button aria-label="Crear recordatorio" />}>
          <BellRing />
          <span className="hidden sm:inline">Recordatorio</span>
          <span className="sr-only">Crear recordatorio</span>
        </DialogTrigger>
        <DialogContent className="max-h-[calc(100svh-2rem)] w-[calc(100%_-_2rem)] max-w-2xl overflow-y-auto">
          <form
            onSubmit={(event) => void createReminder(event)}
            className="grid min-w-0 gap-4"
          >
            <DialogHeader>
              <DialogTitle>Programar recordatorio</DialogTitle>
              <DialogDescription>
                El bot enviará un DM en la fecha elegida y repetirá la regla que
                definas.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="grid min-w-0 gap-2 text-sm font-medium">
                Anuncio relacionado{" "}
                <span className="font-normal text-muted-foreground">
                  opcional
                </span>
                <Select
                  value={reminderFor}
                  onValueChange={(value) => setReminderFor(value ?? "none")}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Sin anuncio asociado</SelectItem>
                    {announcements
                      .filter((item) => item.status !== "cancelled")
                      .map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.content.slice(0, 55)}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </label>
              <label className="grid min-w-0 gap-2 text-sm font-medium">
                Primer envío
                <LimaDateTimePicker
                  value={reminderDate}
                  onChange={setReminderDate}
                  required
                />
              </label>
            </div>
            <label className="grid gap-2 text-sm font-medium">
              Mensaje
              <Textarea
                value={reminderContent}
                onChange={(event) => setReminderContent(event.target.value)}
                maxLength={2000}
                required
                className="min-h-24"
              />
            </label>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="grid min-w-0 gap-2 text-sm font-medium">
                Repetir
                <Select
                  value={recurrence}
                  onValueChange={(value) => setRecurrence(value as Recurrence)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(recurrenceLabels).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              {(recurrence === "daily" || recurrence === "monthly") && (
                <label className="grid min-w-0 gap-2 text-sm font-medium">
                  Cada {recurrence === "daily" ? "días" : "meses"}
                  <Input
                    type="number"
                    min="1"
                    max="365"
                    value={recurrenceInterval}
                    onChange={(event) =>
                      setRecurrenceInterval(event.target.value)
                    }
                  />
                </label>
              )}
              {recurrence !== "once" && (
                <label className="grid min-w-0 gap-2 text-sm font-medium">
                  Repetir hasta{" "}
                  <span className="font-normal text-muted-foreground">
                    opcional
                  </span>
                  <LimaDateTimePicker
                    value={recurrenceUntil}
                    onChange={setRecurrenceUntil}
                  />
                </label>
              )}
            </div>
            {recurrence === "weekly" && (
              <fieldset className="grid gap-2 rounded-xl border border-border p-3">
                <legend className="px-1 text-sm font-medium">
                  Días de la semana
                </legend>
                <div className="flex flex-wrap gap-x-4 gap-y-2">
                  {weekdayLabels.map((label, day) => (
                    <label
                      key={label}
                      className="flex items-center gap-2 text-sm text-muted-foreground"
                    >
                      <Checkbox
                        checked={recurrenceWeekdays.includes(day)}
                        onCheckedChange={() => toggleWeekday(day)}
                      />
                      {label}
                    </label>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  Si no eliges ninguno, se repetirá el día del primer envío.
                </p>
              </fieldset>
            )}
            <Separator />
            <div className="grid gap-4 md:grid-cols-2">
              <label className="grid min-w-0 gap-2 text-sm font-medium">
                Usuarios{" "}
                <span className="font-normal text-muted-foreground">
                  opcional
                </span>
                <Input
                  value={users}
                  onChange={(event) => setUsers(event.target.value)}
                  placeholder="IDs separados por coma"
                />
              </label>
              <label className="grid min-w-0 gap-2 text-sm font-medium">
                Rol de Discord{" "}
                <span className="font-normal text-muted-foreground">
                  opcional
                </span>
                <Select
                  value={role}
                  onValueChange={(value) => setRole(value ?? "none")}
                  disabled={Boolean(rolesError)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Sin rol</SelectItem>
                    {roles.map((item) => (
                      <SelectItem key={item.id} value={String(item.id)}>
                        {item.name}
                        {item.managed ? " · integración" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {rolesError && (
                  <span className="break-words text-xs font-normal text-destructive">
                    No se pudieron cargar los roles: {rolesError}
                  </span>
                )}
              </label>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                type="button"
                onClick={() => setReminderOpen(false)}
              >
                Cancelar
              </Button>
              <Button type="submit" disabled={busy}>
                <CalendarClock />
                Programar
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );

  async function request(path: string, init: RequestInit = {}) {
    const isForm = init.body instanceof FormData;
    const response = await fetch(`${api}${path}`, {
      ...init,
      cache: "no-store",
      headers: {
        ...(isForm ? {} : { "Content-Type": "application/json" }),
        ...(init.headers ?? {}),
      },
    });
    if (!response.ok) {
      const body = await response
        .json()
        .catch(() => ({ detail: "Error inesperado" }));
      throw new Error(body.detail ?? "Error inesperado");
    }
    return response;
  }

  async function loadAnnouncements() {
    try {
      setBusy(true);
      const [announcementsResponse, remindersResponse] = await Promise.all([
        request("/announcements"),
        request("/reminders"),
      ]);
      const loaded = (await announcementsResponse.json()) as Announcement[];
      const loadedReminders = (await remindersResponse.json()) as Reminder[];
      setAnnouncements(loaded);
      setStandaloneReminders(loadedReminders);
      setMessage(
        loaded.length || loadedReminders.length
          ? ""
          : "Aún no hay anuncios ni recordatorios.",
      );
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "No se pudieron cargar los anuncios.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function interpretSchedule(
    instruction: string,
    setPlan: (plan: SchedulePlan | null) => void,
  ) {
    if (!instruction.trim())
      throw new Error("Escribe cuándo debe enviarse el mensaje.");
    setBusy(true);
    try {
      const response = await request("/schedules/parse", {
        method: "POST",
        body: JSON.stringify({ instruction }),
      });
      const plan = (await response.json()) as SchedulePlan;
      setPlan(plan);
      setMessage(`Programación confirmada: ${plan.summary}`);
    } finally {
      setBusy(false);
    }
  }

  function changedSchedule(
    value: string,
    setValue: (value: string) => void,
    setPlan: (plan: SchedulePlan | null) => void,
  ) {
    setValue(value);
    setPlan(null);
  }

  async function createAnnouncement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      if (announcementWhen.trim() && !announcementPlan) {
        throw new Error("Interpreta y confirma primero la fecha del anuncio.");
      }
      const form = new FormData();
      form.set("content", content.trim());
      form.set("channel_ids", JSON.stringify(parseIds(channels)));
      if (announcementPlan) {
        form.set("scheduled_for", announcementPlan.scheduled_for);
        form.set("recurrence", announcementPlan.recurrence);
      }
      announcementFiles.forEach((file) => form.append("files", file));
      setBusy(true);
      await request("/announcements/upload", { method: "POST", body: form });
      setContent("");
      setChannels("");
      setAnnouncementWhen("");
      setAnnouncementPlan(null);
      setAnnouncementFiles([]);
      setMessage("Anuncio guardado y en cola de publicación.");
      await loadAnnouncements();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "No se pudo crear el anuncio.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function createReminder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      if (!reminderPlan)
        throw new Error(
          "Interpreta y confirma primero la fecha del recordatorio.",
        );
      const userIds = users.trim() ? parseIds(users) : [];
      const roleId = role.trim() ? Number(role.trim()) : undefined;
      if (!userIds.length && !roleId)
        throw new Error("Indica usuarios, un rol, o ambos.");
      if (
        roleId !== undefined &&
        (!Number.isSafeInteger(roleId) || roleId <= 0)
      )
        throw new Error("El ID de rol no es válido.");
      const form = new FormData();
      form.set("content", reminderContent.trim());
      form.set("scheduled_for", reminderPlan.scheduled_for);
      form.set("recurrence", reminderPlan.recurrence);
      form.set("user_ids", JSON.stringify(userIds));
      if (roleId) form.set("role_id", String(roleId));
      if (reminderFor) form.set("announcement_id", reminderFor);
      reminderFiles.forEach((file) => form.append("files", file));
      setBusy(true);
      await request("/reminders/upload", { method: "POST", body: form });
      setReminderContent("");
      setReminderWhen("");
      setReminderPlan(null);
      setReminderFiles([]);
      setUsers("");
      setRole("");
      setMessage(
        "Recordatorio guardado. El bot enviará el DM al llegar la fecha.",
      );
      await loadAnnouncements();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "No se pudo programar el recordatorio.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function cancelAnnouncement(id: string) {
    if (
      !window.confirm(
        "¿Cancelar este anuncio y todos sus recordatorios pendientes?",
      )
    )
      return;
    try {
      setBusy(true);
      await request(`/announcements/${id}`, { method: "DELETE" });
      setMessage("Anuncio cancelado.");
      await loadAnnouncements();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "No se pudo cancelar el anuncio.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function cancelReminder(id: string) {
    if (!window.confirm("¿Cancelar este recordatorio pendiente?")) return;
    try {
      setBusy(true);
      await request(`/reminders/${id}`, { method: "DELETE" });
      setMessage("Recordatorio cancelado.");
      await loadAnnouncements();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "No se pudo cancelar el recordatorio.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="announcement-page">
      <header className="announcement-header">
        <div>
          <Link href="/" className="back-link">
            ← Biblioteca RAG
          </Link>
          <h1>Anuncios y recordatorios</h1>
          <p>
            Describe cuándo enviarlo; el modelo propone la fecha y tú la
            confirmas antes de guardar.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void loadAnnouncements()}
          disabled={busy}
        >
          Actualizar
        </button>
      </header>
      <section className="announcement-grid">
        <form
          className="announcement-card"
          onSubmit={(event) => void createAnnouncement(event)}
        >
          <h2>Nuevo anuncio</h2>
          <label>
            Mensaje
            <textarea
              value={content}
              onChange={(event) => setContent(event.target.value)}
              maxLength={2000}
              required
            />
          </label>
          <label>
            Canales (IDs separados por coma)
            <input
              value={channels}
              onChange={(event) => setChannels(event.target.value)}
              placeholder="123..., 456..."
              required
            />
          </label>
          <label>
            ¿Cuándo?
            <textarea
              className="schedule-input"
              value={announcementWhen}
              onChange={(event) =>
                changedSchedule(
                  event.target.value,
                  setAnnouncementWhen,
                  setAnnouncementPlan,
                )
              }
              placeholder="Ej.: el próximo lunes a las 9:30, repetir cada semana"
            />
          </label>
          <div className="schedule-actions">
            <button
              type="button"
              onClick={() =>
                void interpretSchedule(
                  announcementWhen,
                  setAnnouncementPlan,
                ).catch((error: Error) => setMessage(error.message))
              }
              disabled={busy || !announcementWhen.trim()}
            >
              Interpretar fecha
            </button>
            {announcementPlan && (
              <strong className="schedule-preview">
                ✓ {announcementPlan.summary}
              </strong>
            )}
          </div>
          <label className="file-input">
            Adjuntos opcionales (máx. 10; 8 MB c/u, 20 MB total)
            <input
              type="file"
              multiple
              onChange={(event) =>
                setAnnouncementFiles(Array.from(event.target.files ?? []))
              }
            />
          </label>
          {announcementFiles.length > 0 && (
            <p className="selected-files">
              📎 {announcementFiles.map((file) => file.name).join(", ")}
            </p>
          )}
          <button className="save-button" type="submit" disabled={busy}>
            Guardar anuncio
            {announcementPlan ? " programado" : " y publicar ahora"}
          </button>
        </form>
        <form
          className="announcement-card"
          onSubmit={(event) => void createReminder(event)}
        >
          <h2>Nuevo recordatorio privado</h2>
          <label>
            Anuncio relacionado (opcional)
            <select
              value={reminderFor}
              onChange={(event) => setReminderFor(event.target.value)}
            >
              <option value="">Sin anuncio asociado</option>
              {announcements
                .filter((item) => item.status !== "cancelled")
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.content.slice(0, 70)} · {item.id.slice(0, 8)}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Mensaje
            <textarea
              value={reminderContent}
              onChange={(event) => setReminderContent(event.target.value)}
              maxLength={2000}
              required
            />
          </label>
          <label>
            ¿Cuándo?
            <textarea
              className="schedule-input"
              value={reminderWhen}
              onChange={(event) =>
                changedSchedule(
                  event.target.value,
                  setReminderWhen,
                  setReminderPlan,
                )
              }
              placeholder="Ej.: mañana a las 18:00; todos los días"
              required
            />
          </label>
          <div className="schedule-actions">
            <button
              type="button"
              onClick={() =>
                void interpretSchedule(reminderWhen, setReminderPlan).catch(
                  (error: Error) => setMessage(error.message),
                )
              }
              disabled={busy || !reminderWhen.trim()}
            >
              Interpretar fecha
            </button>
            {reminderPlan && (
              <strong className="schedule-preview">
                ✓ {reminderPlan.summary}
              </strong>
            )}
          </div>
          <label>
            Usuarios (IDs opcionales, separados por coma)
            <input
              value={users}
              onChange={(event) => setUsers(event.target.value)}
              placeholder="123..., 456..."
            />
          </label>
          <label>
            Rol (ID opcional)
            <input
              value={role}
              onChange={(event) => setRole(event.target.value)}
              placeholder="123..."
            />
          </label>
          <label className="file-input">
            Adjuntos opcionales
            <input
              type="file"
              multiple
              onChange={(event) =>
                setReminderFiles(Array.from(event.target.files ?? []))
              }
            />
          </label>
          {reminderFiles.length > 0 && (
            <p className="selected-files">
              📎 {reminderFiles.map((file) => file.name).join(", ")}
            </p>
          )}
          <button className="save-button" type="submit" disabled={busy}>
            Programar recordatorio
          </button>
        </form>
      </section>
      {message && <p className="announcement-message">{message}</p>}
      <section className="announcement-list" aria-label="Anuncios registrados">
        {standaloneReminders.length > 0 && (
          <article className="announcement-item">
            <h2>Recordatorios independientes</h2>
            {standaloneReminders.map((reminder) => (
              <div className="reminder" key={reminder.id}>
                <div className="announcement-item-head">
                  <strong>
                    {reminder.status} · {formatDate(reminder.scheduled_for)} ·{" "}
                    {recurrenceLabel[reminder.recurrence]}
                  </strong>
                  {reminder.status === "scheduled" && (
                    <button
                      className="delete-button"
                      type="button"
                      disabled={busy}
                      onClick={() => void cancelReminder(reminder.id)}
                    >
                      Cancelar
                    </button>
                  )}
                </div>
                <p>{reminder.content}</p>
                <AttachmentNames attachments={reminder.attachments} />
                <small>
                  {reminder.target_role_id
                    ? `Rol ${reminder.target_role_id}`
                    : ""}{" "}
                  {reminder.recipients
                    .map(
                      (recipient) =>
                        ` · ${recipient.user_id}: ${recipient.status}`,
                    )
                    .join("")}
                </small>
              </div>
            ))}
          </article>
        )}
        {announcements.map((announcement) => (
          <article className="announcement-item" key={announcement.id}>
            <div className="announcement-item-head">
              <div>
                <span className={`status status-${announcement.status}`}>
                  {announcement.status}
                </span>
                <time>Creado: {formatDate(announcement.created_at)}</time>
              </div>
              {announcement.status !== "cancelled" && (
                <button
                  className="delete-button"
                  type="button"
                  disabled={busy}
                  onClick={() => void cancelAnnouncement(announcement.id)}
                >
                  Cancelar
                </button>
              )}
            </div>
            <p>{announcement.content}</p>
            <AttachmentNames attachments={announcement.attachments} />
            <code>{announcement.id}</code>
            <h3>Entregas · {recurrenceLabel[announcement.recurrence]}</h3>
            <ul>
              {announcement.channels.map((channel) => (
                <li key={channel.channel_id}>
                  Canal #{channel.channel_id} · <b>{channel.status}</b> ·{" "}
                  {formatDate(channel.scheduled_for)}
                  {channel.error ? ` · ${channel.error}` : ""}
                </li>
              ))}
            </ul>
            {announcement.reminders.length > 0 && (
              <>
                <h3>Recordatorios</h3>
                {announcement.reminders.map((reminder) => (
                  <div className="reminder" key={reminder.id}>
                    <strong>
                      {reminder.status} · {formatDate(reminder.scheduled_for)} ·{" "}
                      {recurrenceLabel[reminder.recurrence]}
                    </strong>
                    <p>{reminder.content}</p>
                    <AttachmentNames attachments={reminder.attachments} />
                    <small>
                      {reminder.target_role_id
                        ? `Rol ${reminder.target_role_id}`
                        : ""}{" "}
                      {reminder.recipients
                        .map(
                          (recipient) =>
                            ` · ${recipient.user_id}: ${recipient.status}`,
                        )
                        .join("")}
                    </small>
                  </div>
                ))}
              </>
            )}
          </article>
        ))}
      </section>
    </main>
  );
}

function EmptyState({
  icon,
  title,
  description,
}: {
  icon: ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="grid place-items-center gap-2 rounded-xl border border-dashed border-border p-10 text-center text-muted-foreground">
      <span className="text-primary">{icon}</span>
      <strong className="text-sm text-foreground">{title}</strong>
      <p className="max-w-56 text-xs leading-5">{description}</p>
    </div>
  );
}
