"use client";

import { type ChangeEvent, type KeyboardEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

type DocumentSummary = {
  id: string;
  source: string;
  title: string;
  updated_at: string;
};

type DocumentContent = DocumentSummary & { content: string; reconstructed?: boolean };

const api = "/api";
const blankDocument = (): DocumentContent => ({
  id: "",
  source: "nuevo-documento.md",
  title: "Nuevo documento",
  updated_at: "",
  content: "# Nuevo documento\n\nEscribe aquí el conocimiento que debe usar el bot.",
});

export default function Home() {
  const router = useRouter();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [document, setDocument] = useState<DocumentContent>(blankDocument);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [message, setMessage] = useState("Cargando biblioteca…");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void loadDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function request(path: string, init: RequestInit = {}) {
    const response = await fetch(`${api}${path}`, { ...init, cache: "no-store" });
    if (!response.ok) {
      const body = await response.json().catch(() => ({ detail: "Error inesperado" }));
      throw new Error(body.detail ?? "Error inesperado");
    }
    return response;
  }

  async function loadDocuments() {
    try {
      setBusy(true);
      const response = await request("/documents");
      setDocuments(await response.json());
      setMessage("");
    } catch (error) {
      setDocuments([]);
      setMessage(error instanceof Error ? error.message : "No se pudo cargar la biblioteca.");
    } finally {
      setBusy(false);
    }
  }

  async function openDocument(summary: DocumentSummary) {
    try {
      setBusy(true);
      const response = await request(`/documents/${encodeURIComponent(summary.id)}`);
      const opened: DocumentContent = await response.json();
      setDocument({ ...opened, updated_at: summary.updated_at });
      setSavedId(summary.id);
      setMessage(
        opened.reconstructed
          ? "Borrador reconstruido desde chunks antiguos. Revísalo y guarda para migrarlo al editor."
          : "",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo abrir el documento.");
    } finally {
      setBusy(false);
    }
  }

  async function saveDocument() {
    if (!document.content.trim()) {
      setMessage("Escribe contenido antes de guardar.");
      return;
    }
    try {
      setBusy(true);
      const data = new FormData();
      data.append("content", document.content);
      data.append("title", document.title.trim() || "Documento sin título");
      data.append("source", document.source.trim() || "documento.md");
      if (!savedId && document.id.trim()) data.append("document_id", document.id.trim());

      const endpoint = savedId ? `/documents/${encodeURIComponent(savedId)}` : "/documents";
      const response = await request(endpoint, { method: savedId ? "PUT" : "POST", body: data });
      const result = await response.json();
      setSavedId(result.id);
      setDocument((current) => ({ ...current, id: result.id, title: result.title }));
      setMessage(`Guardado · ${result.chunks} fragmentos listos para el bot.`);
      await loadDocuments();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo guardar el documento.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteDocument() {
    if (!savedId || !window.confirm(`¿Eliminar "${document.title}" de la biblioteca?`)) return;
    try {
      setBusy(true);
      await request(`/documents/${encodeURIComponent(savedId)}`, { method: "DELETE" });
      setDocument(blankDocument());
      setSavedId(null);
      setMessage("Documento eliminado de Qdrant.");
      await loadDocuments();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo eliminar el documento.");
    } finally {
      setBusy(false);
    }
  }

  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const content = await file.text();
      setDocument({
        id: file.name.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""),
        source: file.name,
        title: firstHeading(content) || file.name.replace(/\.[^.]+$/, ""),
        updated_at: "",
        content,
      });
      setSavedId(null);
      setMessage(`Importado: ${file.name}. Revisa el texto y guarda.`);
    } catch {
      setMessage("No se pudo leer el archivo. Debe ser texto UTF-8.");
    } finally {
      event.target.value = "";
    }
  }

  function newDocument() {
    setDocument(blankDocument());
    setSavedId(null);
    setMessage("Documento nuevo sin guardar.");
  }

  function handleKeyboardShortcut(event: KeyboardEvent<HTMLElement>) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (!busy) void saveDocument();
    }
  }

  async function logout() {
    await fetch("/auth/logout", { method: "POST" });
    router.replace("/login");
    router.refresh();
  }

  return (
    <main className="workspace" onKeyDown={handleKeyboardShortcut}>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">C</span>
          <div><strong>CosmecitoBot</strong><small>Biblioteca RAG</small></div>
        </div>
        <button className="new-button" type="button" onClick={newDocument}>＋ Nuevo documento</button>
        <label className="import-button">
          Importar archivo
          <input type="file" accept=".md,.markdown,.txt,text/markdown,text/plain" onChange={importFile} />
        </label>
        <div className="library-header"><span>DOCUMENTOS</span><button type="button" onClick={() => void loadDocuments()} disabled={busy}>↻</button></div>
        <nav className="document-list" aria-label="Documentos indexados">
          {documents.length === 0 ? <p>Aún no hay documentos.</p> : documents.map((item) => (
            <button
              key={item.id}
              type="button"
              className={savedId === item.id ? "document-item active" : "document-item"}
              onClick={() => void openDocument(item)}
            >
              <strong>{item.title}</strong><span>{item.source}</span>
            </button>
          ))}
        </nav>
      </aside>

      <section className="editor-area">
        <header className="topbar">
          <div><span className="status-dot" />{savedId ? "Documento indexado" : "Borrador"}</div>
          <div className="topbar-actions">
            <Link className="topbar-link" href="/announcements">Anuncios</Link>
            <button type="button" className="logout-button" onClick={() => void logout()}>Salir</button>
            {savedId && <button type="button" className="delete-button" onClick={() => void deleteDocument()} disabled={busy}>Eliminar</button>}
            <button type="button" className="save-button" onClick={() => void saveDocument()} disabled={busy}>{busy ? "Guardando…" : "Guardar cambios"}</button>
          </div>
        </header>

        <div className="editor-shell">
          <div className="metadata">
            <input className="title-input" value={document.title} onChange={(event) => setDocument({ ...document, title: event.target.value })} placeholder="Título del documento" />
            <div className="metadata-row">
              <label>Origen<input value={document.source} onChange={(event) => setDocument({ ...document, source: event.target.value })} placeholder="material-semana-1.md" /></label>
              <label>Identificador<input value={document.id} onChange={(event) => setDocument({ ...document, id: event.target.value })} disabled={Boolean(savedId)} placeholder="semana-1" /></label>
            </div>
          </div>
          <div className="editor-label"><span>MARKDOWN</span><span>{document.content.length.toLocaleString()} caracteres</span></div>
          <textarea value={document.content} onChange={(event) => setDocument({ ...document, content: event.target.value })} spellCheck={false} aria-label="Editor Markdown" />
          <footer className="editor-footer"><span>Usa # para títulos y separa párrafos con una línea vacía.</span>{message && <span className="message">{message}</span>}</footer>
        </div>
      </section>
    </main>
  );
}

function firstHeading(content: string) {
  return content.match(/^#\s+(.+?)\s*$/m)?.[1] ?? "";
}
