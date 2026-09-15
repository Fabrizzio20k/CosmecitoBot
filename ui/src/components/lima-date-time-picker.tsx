"use client";

import { es } from "date-fns/locale";
import { CalendarIcon, Clock3 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

type LimaDateTimePickerProps = { value: string; onChange: (value: string) => void; placeholder?: string; required?: boolean };

function pad(value: number) { return String(value).padStart(2, "0"); }
function dateFromValue(value: string) { if (!value) return undefined; const [year, month, day] = value.slice(0, 10).split("-").map(Number); return new Date(year, month - 1, day, 12); }
function displayValue(value: string) { if (!value) return "Elegir fecha y hora"; return new Intl.DateTimeFormat("es-PE", { dateStyle: "medium", timeStyle: "short", timeZone: "America/Lima" }).format(new Date(`${value}:00-05:00`)); }

export function LimaDateTimePicker({ value, onChange, placeholder = "Elegir fecha y hora", required }: LimaDateTimePickerProps) {
  const selected = dateFromValue(value);
  const time = value.slice(11) || "09:00";
  return <div className="grid grid-cols-[1fr_auto] gap-2"><Popover><PopoverTrigger render={<Button variant="outline" className="h-9 min-w-0 justify-start font-normal" />}><CalendarIcon /> <span className={value ? "truncate" : "truncate text-muted-foreground"}>{value ? displayValue(value) : placeholder}</span></PopoverTrigger><PopoverContent align="start" className="w-auto p-0"><Calendar mode="single" selected={selected} onSelect={(day) => { if (day) onChange(`${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}T${time}`); }} locale={es} timeZone="America/Lima" /></PopoverContent></Popover><label className="relative"><Clock3 className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" /><Input type="time" required={required} value={time} onChange={(event) => { const date = value.slice(0, 10); if (date) onChange(`${date}T${event.target.value}`); }} className="h-9 w-28 pl-8" aria-label="Hora Lima" /></label></div>;
}
