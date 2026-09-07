import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Download,
  FileText,
  MessagesSquare,
  Paperclip,
  Play,
  Trash2,
  TriangleAlert,
  Upload,
} from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, apiBlob } from "../lib/api";
import { conversationKey, mergeConversationState } from "../lib/conversation";
import {
  archivosDelProyecto,
  actualizarProyecto,
  conversacionesDelProyecto,
  projectConversationsKey,
  projectFilesKey,
  projectsKey,
  reanudarConversacion,
  sacarDelProyecto,
  subirAlProyecto,
} from "../lib/proyectos";
import type { ConversationState, UserFile } from "../types";

const formatBytes = (bytes: number) => {
  if (bytes < 1_000) return `${bytes} B`;
  if (bytes < 1_000_000) return `${(bytes / 1_000).toFixed(1)} KB`;
  if (bytes < 1_000_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
  return `${(bytes / 1_000_000_000).toFixed(1)} GB`;
};

const FECHA = new Intl.DateTimeFormat("es-ES", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

const descargar = async (file: UserFile) => {
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

/**
 * Un proyecto por dentro: lo que se le ha subido y lo que se ha hablado en él.
 *
 * Las dos listas están en la misma pantalla porque son la misma cosa vista de
 * dos maneras —el material y lo que se dijo sobre él—, y separarlas obligaba a
 * recordar en cuál de las dos pestañas estaba lo que buscas.
 */
export function ProjectDetailPage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const navigate = useNavigate();
  const fileInput = useRef<HTMLInputElement>(null);
  const [aviso, setAviso] = useState("");

  const archivos = useQuery({
    queryKey: projectFilesKey(id),
    queryFn: () => archivosDelProyecto(id),
    enabled: Boolean(id),
  });
  const conversaciones = useQuery({
    queryKey: projectConversationsKey(id),
    queryFn: () => conversacionesDelProyecto(id),
    enabled: Boolean(id),
  });
  const proyecto = archivos.data?.proyecto ?? conversaciones.data?.proyecto;

  const subir = useMutation({
    mutationFn: async (elegidos: FileList) => {
      for (const archivo of Array.from(elegidos)) {
        await subirAlProyecto(id, archivo);
      }
    },
    onSuccess: async () => {
      setAviso("Archivo añadido al proyecto.");
      await Promise.all([
        client.invalidateQueries({ queryKey: projectFilesKey(id) }),
        client.invalidateQueries({ queryKey: projectsKey }),
        client.invalidateQueries({ queryKey: ["files"] }),
      ]);
    },
  });
  const sacar = useMutation({
    mutationFn: (fileId: string) => sacarDelProyecto(id, fileId),
    onSuccess: async () => {
      setAviso("El archivo sale del proyecto, pero sigue en tus archivos.");
      await Promise.all([
        client.invalidateQueries({ queryKey: projectFilesKey(id) }),
        client.invalidateQueries({ queryKey: projectsKey }),
        client.invalidateQueries({ queryKey: ["files"] }),
      ]);
    },
  });
  const describir = useMutation({
    mutationFn: (descripcion: string) => actualizarProyecto(id, { descripcion }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: projectFilesKey(id) }),
        client.invalidateQueries({ queryKey: projectsKey }),
      ]);
    },
  });
  const reanudar = useMutation({
    mutationFn: (conversationId: string) => reanudarConversacion(conversationId),
    onSuccess: (estado) => {
      client.setQueryData<ConversationState>(conversationKey, (current) =>
        mergeConversationState(current, estado),
      );
      navigate("/hilo");
    },
  });

  const error =
    [subir.error, sacar.error, reanudar.error].find(Boolean) instanceof ApiError
      ? ([subir.error, sacar.error, reanudar.error].find(Boolean) as ApiError).message
      : null;

  if (archivos.isError && conversaciones.isError) {
    return (
      <section className="page">
        <p className="inline-error">No se pudo abrir el proyecto.</p>
        <Link className="secondary-button" to="/taller/proyectos">
          <ArrowLeft size={16} /> Volver a proyectos
        </Link>
      </section>
    );
  }

  return (
    <section className="page project-detail">
      <header className="page-header">
        <div>
          <Link className="back-link" to="/taller/proyectos">
            <ArrowLeft size={15} /> Proyectos
          </Link>
          <h1>{proyecto?.nombre ?? "Proyecto"}</h1>
          <p>
            {proyecto?.descripcion || "Sin descripción todavía."}
            {proyecto && !proyecto.carpeta && (
              <span className="project-warning">
                {" "}
                <TriangleAlert size={13} /> Su carpeta ya no existe: puede guardar
                cosas, pero no recibir encargos.
              </span>
            )}
          </p>
        </div>
        <button
          className="secondary-button"
          onClick={() => {
            const texto = window.prompt(
              "¿De qué va este proyecto?",
              proyecto?.descripcion ?? "",
            );
            if (texto !== null) describir.mutate(texto);
          }}
          disabled={describir.isPending}
        >
          <FileText size={16} /> Editar descripción
        </button>
      </header>

      {aviso && <p className="success-message" role="status">{aviso}</p>}
      {error && <p className="inline-error" role="alert">{error}</p>}

      <div className="project-sections">
        <section className="project-section">
          <header>
            <h2><Paperclip size={16} /> Archivos</h2>
            <input
              ref={fileInput}
              className="sr-only"
              type="file"
              multiple
              aria-label="Subir archivos al proyecto"
              onChange={(event) => {
                if (event.target.files?.length) subir.mutate(event.target.files);
                event.target.value = "";
              }}
            />
            <button
              className="primary-button"
              onClick={() => fileInput.current?.click()}
              disabled={subir.isPending}
            >
              <Upload size={16} /> {subir.isPending ? "Subiendo…" : "Subir archivo"}
            </button>
          </header>
          {archivos.isPending ? (
            <p className="muted">Cargando archivos…</p>
          ) : archivos.data?.archivos.length ? (
            <ul className="project-file-list">
              {archivos.data.archivos.map((archivo) => (
                <li key={archivo.id}>
                  <FileText size={16} aria-hidden />
                  <div>
                    <strong>{archivo.name}</strong>
                    <small>
                      {formatBytes(archivo.size_bytes)} ·{" "}
                      {FECHA.format(new Date(archivo.created_at * 1000))}
                    </small>
                  </div>
                  <button
                    className="icon-button"
                    aria-label={`Descargar ${archivo.name}`}
                    onClick={() => void descargar(archivo)}
                  >
                    <Download size={16} />
                  </button>
                  <button
                    className="icon-button danger-button"
                    aria-label={`Sacar ${archivo.name} del proyecto`}
                    disabled={sacar.isPending}
                    onClick={() => sacar.mutate(archivo.id)}
                  >
                    <Trash2 size={16} />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">
              Nada subido todavía. Lo que subas aquí queda a mano cuando le
              hables a Vibi de este proyecto.
            </p>
          )}
        </section>

        <section className="project-section">
          <header>
            <h2><MessagesSquare size={16} /> Conversaciones</h2>
          </header>
          {conversaciones.isPending ? (
            <p className="muted">Cargando conversaciones…</p>
          ) : conversaciones.data?.conversaciones.length ? (
            <ul className="project-conversation-list">
              {conversaciones.data.conversaciones.map((conversacion) => (
                <li key={conversacion.id}>
                  <div>
                    <strong>{conversacion.titulo ?? "Sin título"}</strong>
                    <small>
                      {conversacion.mensajes} mensajes ·{" "}
                      {FECHA.format(new Date(conversacion.updated_at * 1000))}
                      {conversacion.estado === "activa" && " · en curso"}
                    </small>
                  </div>
                  <button
                    className="secondary-button"
                    disabled={reanudar.isPending || conversacion.estado === "activa"}
                    onClick={() => reanudar.mutate(conversacion.id)}
                  >
                    <Play size={15} />
                    {conversacion.estado === "activa" ? "Abierta" : "Retomar"}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">
              Ninguna guardada aún. Desde el hilo, «Guardar en proyecto» la deja
              aquí sin cerrarla.
            </p>
          )}
        </section>
      </div>
    </section>
  );
}
