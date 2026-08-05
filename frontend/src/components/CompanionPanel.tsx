import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  Inbox,
  ListTodo,
  ShieldAlert,
  Upload,
  Trash2,
} from "lucide-react";
import { useEffect, useState, type DragEvent, type FormEvent } from "react";

import { AprobacionesPanel } from "./AprobacionesPanel";
import { StatusBadge } from "./StatusBadge";
import { apiBlob, apiFetch } from "../lib/api";
import {
  connectCompanionConsole,
  forgetCompanionUserToken,
  loadCompanionSettings,
} from "../lib/companionApi";
import { nodeApprovalsKey } from "../lib/nodeApprovals";
import { orderTasks, taskKeys } from "../lib/tasks";
import { useEvents } from "../lib/useEvents";
import type { NodeOrder, Task, UserFile } from "../types";

interface FilesResponse {
  archivos: UserFile[];
}

type Seccion = "aprobaciones" | "bandeja" | "archivos";

const formatBytes = (bytes: number) => {
  if (bytes < 1_000) return `${bytes} B`;
  if (bytes < 1_000_000) return `${(bytes / 1_000).toFixed(1)} KB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
};

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
 * La consola de Morgana dentro del escritorio: lo mismo que la PWA, en la
 * ventana que ya tienes abierta. Vive en una ventana aparte de la cara porque
 * la cara mide 320×360 y no da para una bandeja.
 */
export function CompanionPanel() {
  useEvents();
  // Arranca en la bandeja: desde que se quitaron las confirmaciones, Permisos
  // no puede llegar a tener nada y aterrizar ahí sería aterrizar en un vacío.
  // La pestaña se queda por si algún día vuelven.
  const [seccion, setSeccion] = useState<Seccion>("bandeja");
  const [conectada, setConectada] = useState(() =>
    Boolean(loadCompanionSettings()?.userToken),
  );

  // El JWT dura treinta días. Cuando caduca, cualquier petición devuelve 401 y
  // el cliente compartido avisa por aquí: mejor volver a pedir la contraseña
  // que enseñar tres secciones vacías sin explicar por qué.
  useEffect(() => {
    const caducada = () => {
      forgetCompanionUserToken();
      setConectada(false);
    };
    window.addEventListener("morgana:unauthorized", caducada);
    return () => window.removeEventListener("morgana:unauthorized", caducada);
  }, []);

  const aprobaciones = useQuery<NodeOrder[]>({
    queryKey: nodeApprovalsKey,
    queryFn: () =>
      apiFetch<{ ordenes: NodeOrder[] }>("/api/nodos/aprobaciones").then(
        (payload) => payload.ordenes,
      ),
    enabled: conectada,
  });
  const pendientes = aprobaciones.data?.length ?? 0;

  if (!conectada) {
    return <ConectarConsola onConectada={() => setConectada(true)} />;
  }

  return (
    <main className="panel-shell">
      <nav className="panel-tabs" aria-label="Secciones">
        <button
          type="button"
          className={seccion === "aprobaciones" ? "activa" : ""}
          onClick={() => setSeccion("aprobaciones")}
        >
          <ShieldAlert size={15} aria-hidden />
          Permisos
          {pendientes > 0 && <span className="panel-pip">{pendientes}</span>}
        </button>
        <button
          type="button"
          className={seccion === "bandeja" ? "activa" : ""}
          onClick={() => setSeccion("bandeja")}
        >
          <ListTodo size={15} aria-hidden />
          Bandeja
        </button>
        <button
          type="button"
          className={seccion === "archivos" ? "activa" : ""}
          onClick={() => setSeccion("archivos")}
        >
          <Inbox size={15} aria-hidden />
          Archivos
        </button>
      </nav>

      <div className="panel-body">
        {seccion === "aprobaciones" && <SeccionAprobaciones />}
        {seccion === "bandeja" && <SeccionBandeja />}
        {seccion === "archivos" && <SeccionArchivos />}
      </div>
    </main>
  );
}

/**
 * Lo único que le falta a un companion que ya habla: la credencial de usuario.
 *
 * No se reutiliza la pantalla de vincular entera porque el servidor y el
 * nombre del PC ya están guardados y siguen siendo válidos; lo que caducó —o
 * lo que nunca se llegó a pedir— es la sesión, y para eso basta la contraseña.
 */
function ConectarConsola({ onConectada }: { onConectada: () => void }) {
  const settings = loadCompanionSettings();
  const [name, setName] = useState(settings?.userName ?? "");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      await connectCompanionConsole({ name, password });
      setPassword("");
      onConectada();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "No he podido iniciar sesión.",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <main className="panel-shell">
      <form className="panel-conectar" onSubmit={submit}>
        <h2>Conecta la consola</h2>
        <p>
          Este PC ya habla con Morgana, pero para enseñarte los permisos, la
          bandeja y los archivos necesita tu sesión. La voz sigue funcionando
          mientras tanto.
        </p>
        <label>
          <span>Nombre</span>
          <input
            autoComplete="username"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
        </label>
        <label>
          <span>Contraseña</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error && <p className="panel-error">{error}</p>}
        <button disabled={pending}>
          {pending ? "Conectando…" : "Conectar"}
        </button>
      </form>
    </main>
  );
}

function SeccionAprobaciones() {
  const query = useQuery<NodeOrder[]>({
    queryKey: nodeApprovalsKey,
    queryFn: () =>
      apiFetch<{ ordenes: NodeOrder[] }>("/api/nodos/aprobaciones").then(
        (payload) => payload.ordenes,
      ),
  });

  if (query.data?.length) return <AprobacionesPanel />;
  return (
    <p className="panel-vacio">
      Nada esperando permiso. Cuando Morgana quiera ejecutar algo que toque tus
      máquinas, aparecerá aquí antes de hacerlo.
    </p>
  );
}

function SeccionBandeja() {
  const query = useQuery({
    queryKey: taskKeys.list("", ""),
    queryFn: () => apiFetch<Task[]>("/api/tareas?limite=50"),
  });
  const tasks = orderTasks(query.data ?? []);

  if (query.isPending) return <p className="panel-vacio">Cargando…</p>;
  if (!tasks.length) {
    return <p className="panel-vacio">La bandeja está despejada.</p>;
  }

  return (
    <ul className="panel-lista">
      {tasks.map((task) => (
        <li key={task.id} className="panel-tarea">
          <StatusBadge state={task.estado} />
          <p>{task.prompt}</p>
        </li>
      ))}
    </ul>
  );
}

function SeccionArchivos() {
  const client = useQueryClient();
  const [aviso, setAviso] = useState("");
  const [encima, setEncima] = useState(false);

  const query = useQuery({
    queryKey: ["files", "", ""],
    queryFn: () => apiFetch<FilesResponse>("/api/archivos?limite=50"),
  });

  const subir = useMutation({
    mutationFn: (elegido: globalThis.File) => {
      const data = new FormData();
      data.append("archivo", elegido);
      return apiFetch<UserFile>("/api/archivos", { method: "POST", body: data });
    },
    onSuccess: async (file) => {
      setAviso(`${file.name} ya está en todos tus dispositivos.`);
      await client.invalidateQueries({ queryKey: ["files"] });
    },
    onError: (error: Error) => setAviso(error.message),
  });

  const borrar = useMutation({
    mutationFn: (file: UserFile) =>
      apiFetch<void>(`/api/archivos/${file.id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["files"] }),
  });

  // Arrastrar un archivo encima de la ventana lo sube: es la gracia de tener
  // Morgana en el escritorio y no en una pestaña.
  const soltar = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setEncima(false);
    const archivos = Array.from(event.dataTransfer.files);
    for (const archivo of archivos) subir.mutate(archivo);
  };

  const archivos = query.data?.archivos ?? [];

  return (
    <div
      className={`panel-drop${encima ? " encima" : ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        setEncima(true);
      }}
      onDragLeave={() => setEncima(false)}
      onDrop={soltar}
    >
      <label className="panel-subir">
        <Upload size={15} aria-hidden />
        <span>{subir.isPending ? "Subiendo…" : "Arrastra aquí o elige"}</span>
        <input
          type="file"
          hidden
          onChange={(event) => {
            const elegido = event.target.files?.[0];
            if (elegido) subir.mutate(elegido);
            event.target.value = "";
          }}
        />
      </label>

      {aviso && <p className="panel-aviso">{aviso}</p>}

      {archivos.length ? (
        <ul className="panel-lista">
          {archivos.map((file) => (
            <li key={file.id} className="panel-archivo">
              <div>
                <p>{file.name}</p>
                <span>{formatBytes(file.size_bytes)}</span>
              </div>
              <button
                type="button"
                aria-label={`Descargar ${file.name}`}
                onClick={() => void descargar(file)}
              >
                <Download size={15} />
              </button>
              <button
                type="button"
                aria-label={`Borrar ${file.name}`}
                onClick={() => borrar.mutate(file)}
              >
                <Trash2 size={15} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="panel-vacio">Todavía no hay archivos.</p>
      )}
    </div>
  );
}
