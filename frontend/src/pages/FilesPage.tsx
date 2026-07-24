import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  File,
  FileSearch,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import { useDeferredValue, useState } from "react";

import { ApiError, apiBlob, apiFetch } from "../lib/api";
import type { UserFile } from "../types";

interface FilesResponse {
  archivos: UserFile[];
}

const formatBytes = (bytes: number) => {
  if (bytes < 1_000) return `${bytes} B`;
  if (bytes < 1_000_000) return `${(bytes / 1_000).toFixed(1)} KB`;
  if (bytes < 1_000_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
  return `${(bytes / 1_000_000_000).toFixed(1)} GB`;
};

const downloadFile = async (file: UserFile) => {
  const blob = await apiBlob(file.download_url);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = file.name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
};

export function FilesPage() {
  const client = useQueryClient();
  const [search, setSearch] = useState("");
  const [feedback, setFeedback] = useState("");
  const [downloading, setDownloading] = useState<string | null>(null);
  const deferredSearch = useDeferredValue(search);
  const query = useQuery({
    queryKey: ["files", deferredSearch],
    queryFn: () =>
      apiFetch<FilesResponse>(
        `/api/archivos?consulta=${encodeURIComponent(deferredSearch)}&limite=100`,
      ),
  });
  const upload = useMutation({
    mutationFn: (selected: globalThis.File) => {
      const data = new FormData();
      data.append("archivo", selected);
      return apiFetch<UserFile>("/api/archivos", {
        method: "POST",
        body: data,
      });
    },
    onSuccess: async (file) => {
      setFeedback(`${file.name} ya está disponible en tus dispositivos.`);
      await client.invalidateQueries({ queryKey: ["files"] });
    },
  });
  const remove = useMutation({
    mutationFn: (file: UserFile) =>
      apiFetch<void>(`/api/archivos/${file.id}`, { method: "DELETE" }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["files"] });
    },
  });

  const download = async (file: UserFile) => {
    setDownloading(file.id);
    setFeedback("");
    try {
      await downloadFile(file);
    } catch (reason) {
      setFeedback(
        reason instanceof ApiError
          ? reason.message
          : "No se pudo descargar el archivo.",
      );
    } finally {
      setDownloading(null);
    }
  };

  const error =
    upload.error instanceof ApiError
      ? upload.error.message
      : remove.error instanceof ApiError
        ? remove.error.message
        : null;

  return (
    <section className="page files-page">
      <header className="page-header resource-header">
        <div>
          <p className="eyebrow">Puente multidispositivo</p>
          <h1>Archivos</h1>
          <p>
            Busca en tu espacio del PC principal o sube un archivo para tenerlo
            disponible desde cualquier dispositivo autenticado.
          </p>
        </div>
        <label className="primary-button upload-trigger">
          <Upload size={18} />
          {upload.isPending ? "Subiendo…" : "Subir archivo"}
          <input
            className="sr-only"
            type="file"
            disabled={upload.isPending}
            onChange={(event) => {
              const selected = event.target.files?.[0];
              if (selected) {
                setFeedback("");
                upload.mutate(selected);
              }
              event.target.value = "";
            }}
          />
        </label>
      </header>

      <label className="file-search">
        <Search size={18} />
        <span className="sr-only">Buscar archivos</span>
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Matrícula cuarto de carrera…"
        />
      </label>

      {feedback && <p className="success-message" role="status">{feedback}</p>}
      {error && <p className="inline-error" role="alert">{error}</p>}

      {query.isPending ? (
        <div className="resource-grid"><i className="resource-skeleton" /><i className="resource-skeleton" /></div>
      ) : query.isError ? (
        <p className="inline-error">No se pudo leer tu espacio de archivos.</p>
      ) : query.data?.archivos.length ? (
        <ul className="resource-grid" aria-label="Archivos encontrados">
          {query.data.archivos.map((file) => (
            <li key={file.id} className="resource-card file-card">
              <span className="resource-icon"><File size={22} /></span>
              <div className="resource-copy">
                <h2>{file.name}</h2>
                <p>{file.relative_path ?? "Archivo subido"}</p>
                <span>{formatBytes(file.size_bytes)} · {file.source === "workspace" ? "PC principal" : "Morgana"}</span>
              </div>
              <div className="resource-actions">
                <button
                  className="icon-button"
                  aria-label={`Descargar ${file.name}`}
                  disabled={downloading === file.id}
                  onClick={() => void download(file)}
                >
                  <Download size={18} />
                </button>
                {file.source === "managed" && (
                  <button
                    className="icon-button danger-button"
                    aria-label={`Eliminar ${file.name}`}
                    disabled={remove.isPending}
                    onClick={() => {
                      if (window.confirm(`¿Eliminar ${file.name} de Morgana?`)) {
                        remove.mutate(file);
                      }
                    }}
                  >
                    <Trash2 size={17} />
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <div className="empty-list">
          <FileSearch size={32} />
          <h2>{search ? "Sin coincidencias" : "Tu espacio está vacío"}</h2>
          <p>{search ? "Prueba con menos palabras." : "Sube un archivo o añádelo a tu directorio del PC principal."}</p>
        </div>
      )}
    </section>
  );
}
