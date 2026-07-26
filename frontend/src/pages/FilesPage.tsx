import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ChevronRight,
  Download,
  File,
  FileArchive,
  FileAudio,
  FileCode,
  FileImage,
  FileSearch,
  FileText,
  FileVideo,
  Folder,
  FolderOpen,
  House,
  Search,
  Trash2,
  Upload,
  type LucideIcon,
} from "lucide-react";
import { useDeferredValue, useState, type CSSProperties } from "react";

import { ApiError, apiBlob, apiFetch } from "../lib/api";
import type { UserFile } from "../types";

interface FilesResponse {
  ruta: string;
  carpetas: FileFolder[];
  archivos: UserFile[];
}

interface FileFolder {
  name: string;
  path: string;
}

const formatBytes = (bytes: number) => {
  if (bytes < 1_000) return `${bytes} B`;
  if (bytes < 1_000_000) return `${(bytes / 1_000).toFixed(1)} KB`;
  if (bytes < 1_000_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
  return `${(bytes / 1_000_000_000).toFixed(1)} GB`;
};

// Cada archivo se lee por lo que es: el glifo y su matiz codifican el tipo,
// dentro de la banda fría/violeta de Morgana para no romper la paleta.
const FILE_TYPES: { icon: LucideIcon; hue: number; extensions: string[] }[] = [
  { icon: FileImage, hue: 300, extensions: ["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "avif", "ico"] },
  { icon: FileCode, hue: 228, extensions: ["js", "ts", "tsx", "jsx", "json", "py", "rs", "go", "java", "c", "cpp", "h", "css", "html", "sh", "yml", "yaml", "toml", "xml", "sql"] },
  { icon: FileArchive, hue: 282, extensions: ["zip", "rar", "7z", "tar", "gz", "tgz"] },
  { icon: FileAudio, hue: 248, extensions: ["mp3", "wav", "ogg", "flac", "m4a", "aac"] },
  { icon: FileVideo, hue: 214, extensions: ["mp4", "mov", "mkv", "webm", "avi"] },
  { icon: FileText, hue: 262, extensions: ["md", "txt", "rtf", "pdf", "doc", "docx", "odt", "csv"] },
];

const fileGlyph = (name: string): { Icon: LucideIcon; hue: number } => {
  const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";
  const match = FILE_TYPES.find((type) => type.extensions.includes(ext));
  return match ? { Icon: match.icon, hue: match.hue } : { Icon: File, hue: 262 };
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
  const [currentPath, setCurrentPath] = useState("");
  const [feedback, setFeedback] = useState("");
  const [downloading, setDownloading] = useState<string | null>(null);
  const deferredSearch = useDeferredValue(search);
  const isSearching = Boolean(deferredSearch.trim());
  const query = useQuery({
    queryKey: ["files", deferredSearch, currentPath],
    queryFn: () =>
      apiFetch<FilesResponse>(
        isSearching
          ? `/api/archivos?consulta=${encodeURIComponent(deferredSearch)}&limite=100`
          : `/api/archivos?ruta=${encodeURIComponent(currentPath)}&limite=100`,
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
  const pathParts = currentPath.split("/").filter(Boolean);
  const folders = query.data?.carpetas ?? [];
  const files = query.data?.archivos ?? [];
  const hasEntries = folders.length > 0 || files.length > 0;

  const navigateTo = (path: string) => {
    setCurrentPath(path);
    setFeedback("");
  };

  const navigateBack = () => {
    navigateTo(pathParts.slice(0, -1).join("/"));
  };

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
          placeholder="Buscar en todos los archivos…"
        />
      </label>

      {!isSearching && (
        <div className="file-location">
          <button
            className="icon-button location-back"
            aria-label="Volver a la carpeta anterior"
            disabled={!currentPath}
            onClick={navigateBack}
          >
            <ArrowLeft size={18} />
          </button>
          <nav className="file-breadcrumbs" aria-label="Ruta actual">
            <button onClick={() => navigateTo("")} aria-current={!currentPath ? "page" : undefined}>
              <House size={15} />
              <span>Mi PC</span>
            </button>
            {pathParts.map((part, index) => {
              const path = pathParts.slice(0, index + 1).join("/");
              const isCurrent = index === pathParts.length - 1;
              return (
                <span key={path}>
                  <ChevronRight size={14} />
                  <button onClick={() => navigateTo(path)} aria-current={isCurrent ? "page" : undefined}>
                    {part}
                  </button>
                </span>
              );
            })}
          </nav>
        </div>
      )}

      {isSearching && (
        <div className="search-context" role="status">
          <Search size={15} /> Resultados en todo Mi PC
        </div>
      )}

      {feedback && <p className="success-message" role="status">{feedback}</p>}
      {error && <p className="inline-error" role="alert">{error}</p>}

      {query.isPending ? (
        <div className="resource-grid"><i className="resource-skeleton" /><i className="resource-skeleton" /></div>
      ) : query.isError ? (
        <p className="inline-error">No se pudo leer tu espacio de archivos.</p>
      ) : hasEntries ? (
        <ul className="resource-grid file-explorer" aria-label={isSearching ? "Archivos encontrados" : "Contenido de la carpeta"}>
          {!isSearching && folders.map((folder) => (
            <li key={folder.path} className="resource-card folder-card">
              <button onClick={() => navigateTo(folder.path)}>
                <span className="resource-icon folder-icon"><Folder size={23} /></span>
                <div className="resource-copy">
                  <h2>{folder.name}</h2>
                  <span>Carpeta</span>
                </div>
                <ChevronRight className="folder-chevron" size={18} />
              </button>
            </li>
          ))}
          {files.map((file) => {
            const { Icon, hue } = fileGlyph(file.name);
            return (
            <li key={file.id} className="resource-card file-card">
              <span className="resource-icon file-glyph" style={{ "--file-hue": hue } as CSSProperties}><Icon size={21} /></span>
              <div className="resource-copy">
                <h2>{file.name}</h2>
                {isSearching && <p>{file.relative_path ?? "Archivo subido"}</p>}
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
            );
          })}
        </ul>
      ) : (
        <div className="empty-list">
          {isSearching ? <FileSearch size={32} /> : <FolderOpen size={32} />}
          <h2>{isSearching ? "Sin coincidencias" : currentPath ? "Esta carpeta está vacía" : "Tu espacio está vacío"}</h2>
          <p>{isSearching ? "Prueba con menos palabras." : "Sube un archivo o añádelo a tu directorio del PC principal."}</p>
        </div>
      )}
    </section>
  );
}
