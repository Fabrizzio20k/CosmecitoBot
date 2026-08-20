"use client";

import { type FormEvent, useEffect, useState } from "react";

type Document = {
  id: string;
  source: string;
  title: string;
  updated_at: string;
};

const api = "/api";

export default function Home() {
  const [token, setToken] = useState("");
  const [documents, setDocuments] = useState<Document[]>([]);
  const [documentId, setDocumentId] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [message, setMessage] = useState("Ingresa tu token para ver los documentos.");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (token) void loadDocuments();
    // El token nunca se persiste en el navegador.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function request(path: string, init: RequestInit = {}) {
    const headers = new Headers(init.headers);
    headers.set("X-Admin-Token", token);
    const response = await fetch(`${api}${path}`, { ...init, headers, cache: "no-store" });
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

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setMessage("Elige un archivo Markdown o texto plano.");
      return;
    }

    const data = new FormData();
    data.append("file", file);
    if (title.trim()) data.append("title", title.trim());
    if (!editingId && documentId.trim()) data.append("document_id", documentId.trim());

    try {
      setBusy(true);
      const endpoint = editingId ? `/documents/${encodeURIComponent(editingId)}` : "/documents";
      const response = await request(endpoint, { method: editingId ? "PUT" : "POST", body: data });
      const result = await response.json();
      setMessage(`Guardado: ${result.title} (${result.chunks} fragmentos).`);
      resetForm();
      await loadDocuments();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo guardar el documento.");
    } finally {
      setBusy(false);
    }
  }

  async function removeDocument(document: Document) {
    if (!window.confirm(`¿Quitar "${document.title}" de la biblioteca del bot?`)) return;
    try {
      setBusy(true);
      await request(`/documents/${encodeURIComponent(document.id)}`, { method: "DELETE" });
      setMessage(`Documento eliminado: ${document.title}.`);
      if (editingId === document.id) resetForm();
      await loadDocuments();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo eliminar el documento.");
    } finally {
      setBusy(false);
    }
  }

  function editDocument(document: Document) {
    setEditingId(document.id);
    setDocumentId(document.id);
    setTitle(document.title);
    setFile(null);
    setMessage(`Sube un archivo para reemplazar "${document.title}".`);
  }

  function resetForm() {
    setEditingId(null);
    setDocumentId("");
    setTitle("");
    setFile(null);
  }

  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">COSMECITOBOT · BIBLIOTECA RAG</p>
        <h1>Documentos del bot</h1>
        <p>Sube, reemplaza o elimina el conocimiento que consulta el bot en Discord.</p>
      </section>

      <section className="card token-card">
        <label htmlFor="token">Token de administración</label>
        <input
          id="token"
          type="password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="API_ADMIN_TOKEN"
          autoComplete="off"
        />
      </section>

      <section className="grid">
        <form className="card form-card" onSubmit={submit}>
          <div className="section-heading">
            <h2>{editingId ? "Actualizar documento" : "Añadir documento"}</h2>
            {editingId && <button type="button" className="text-button" onClick={resetForm}>Cancelar</button>}
          </div>

          <label htmlFor="document-id">Identificador</label>
          <input
            id="document-id"
            value={documentId}
            onChange={(event) => setDocumentId(event.target.value)}
            placeholder="semana-1-requisitos"
            disabled={Boolean(editingId)}
          />
          <small>Si lo dejas vacío, se usa el nombre del archivo.</small>

          <label htmlFor="title">Título visible</label>
          <input
            id="title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Semana 1: Requisitos"
          />

          <label htmlFor="file">Archivo (.md, .markdown o .txt)</label>
          <input
            id="file"
            type="file"
            accept=".md,.markdown,.txt,text/markdown,text/plain"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />

          <button type="submit" disabled={busy || !token}>
            {busy ? "Procesando…" : editingId ? "Reemplazar documento" : "Añadir a la biblioteca"}
          </button>
          {message && <p className="message" role="status">{message}</p>}
        </form>

        <section className="card library-card">
          <div className="section-heading">
            <h2>Biblioteca</h2>
            <button type="button" className="text-button" onClick={() => void loadDocuments()} disabled={busy || !token}>
              Actualizar
            </button>
          </div>

          {!token ? (
            <p className="empty">Ingresa el token para consultar la biblioteca.</p>
          ) : documents.length === 0 ? (
            <p className="empty">Aún no hay documentos indexados.</p>
          ) : (
            <ul className="documents">
              {documents.map((document) => (
                <li key={document.id}>
                  <div>
                    <strong>{document.title}</strong>
                    <span>{document.source}</span>
                  </div>
                  <div className="actions">
                    <button type="button" className="text-button" onClick={() => editDocument(document)}>Reemplazar</button>
                    <button type="button" className="danger-button" onClick={() => void removeDocument(document)}>Quitar</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </section>
    </main>
  );
}
