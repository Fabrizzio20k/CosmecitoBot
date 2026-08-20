import os
import time
from dataclasses import dataclass
from threading import Lock

import psutil


@dataclass
class PhaseMetric:
    count: int = 0
    total_seconds: float = 0
    max_seconds: float = 0
    last_seconds: float = 0

    def add(self, seconds: float) -> None:
        self.count += 1
        self.total_seconds += seconds
        self.max_seconds = max(self.max_seconds, seconds)
        self.last_seconds = seconds


class RuntimeMetrics:
    """Métricas ligeras del bot y de los llama-server locales."""

    phase_labels = {
        "retrieval": "Recuperación RAG",
        "query_embedding": "Embedding de consulta",
        "vector_search": "Búsqueda en Qdrant",
        "history_trim": "Limpieza del historial",
        "chat_generation": "Generación del chat",
    }

    def __init__(self) -> None:
        self.process = psutil.Process(os.getpid())
        self.metrics: dict[str, PhaseMetric] = {}
        self.lock = Lock()
        # Inicializa los contadores para que la próxima lectura sea un intervalo real.
        psutil.cpu_percent(interval=None)
        self.process.cpu_percent(interval=None)

    def record(self, phase: str, seconds: float) -> None:
        with self.lock:
            metric = self.metrics.setdefault(phase, PhaseMetric())
            metric.add(seconds)

    def report(self, chat_port: int = 8080, embedding_port: int = 8081) -> str:
        system_cpu = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        bot_memory = self.process.memory_info().rss
        bot_cpu = self.process.cpu_percent(interval=None)
        lines = [
            "**Recursos actuales**",
            f"Bot — CPU: {bot_cpu:.1f}% | RAM: {self._mib(bot_memory):.1f} MiB",
            (
                f"Sistema — CPU: {system_cpu:.1f}% | RAM: {memory.percent:.1f}% "
                f"({self._mib(memory.used):.0f}/{self._mib(memory.total):.0f} MiB)"
            ),
        ]

        for label, port in (("llama chat", chat_port), ("llama embeddings", embedding_port)):
            usage = self._llama_server_usage(port)
            if usage is None:
                lines.append(f"{label} :{port} — no detectado")
            else:
                cpu, rss = usage
                lines.append(f"{label} :{port} — CPU: {cpu:.1f}% | RAM: {self._mib(rss):.1f} MiB")

        with self.lock:
            metrics = {name: PhaseMetric(**vars(metric)) for name, metric in self.metrics.items()}

        lines.append("\n**Tiempos acumulados**")
        if not metrics:
            lines.append("Aún no hay operaciones medidas.")
        else:
            for name, metric in metrics.items():
                label = self.phase_labels.get(name, name)
                average = metric.total_seconds / metric.count
                lines.append(
                    f"{label} — último {self._format_seconds(metric.last_seconds)}, "
                    f"promedio {self._format_seconds(average)}, "
                    f"máximo {self._format_seconds(metric.max_seconds)} ({metric.count}x)"
                )
        return "\n".join(lines)

    def _llama_server_usage(self, port: int) -> tuple[float, int] | None:
        try:
            processes = psutil.process_iter(["name", "cmdline", "memory_info"])
            for process in processes:
                try:
                    info = process.info
                    command = " ".join(info.get("cmdline") or [])
                    name = info.get("name") or ""
                    if "llama-server" not in name and "llama-server" not in command:
                        continue
                    if not self._uses_port(command, port):
                        continue
                    return process.cpu_percent(interval=None), info["memory_info"].rss
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue
        except (psutil.AccessDenied, PermissionError):
            return None
        return None

    def _uses_port(self, command: str, port: int) -> bool:
        tokens = command.split()
        return any(
            token == str(port) and index > 0 and tokens[index - 1] in {"--port", "-p"}
            for index, token in enumerate(tokens)
        )

    def _format_seconds(self, seconds: float) -> str:
        if seconds < 1:
            return f"{seconds * 1_000:.0f} ms"
        return f"{seconds:.2f} s"

    def _mib(self, bytes_value: int) -> float:
        return bytes_value / (1024 * 1024)
