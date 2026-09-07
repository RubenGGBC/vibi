import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import {
  Clock3,
  FolderKanban,
  LogOut,
  MessageSquare,
  Monitor,
  Settings2,
  SquareStack,
  Wrench,
} from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { RailFace } from "./RailFace";
import { apiFetch } from "../lib/api";
import { clearToken } from "../lib/auth";
import { fetchNodos, nodosKey } from "../lib/nodos";
import { fetchNodeApprovals, nodeApprovalsKey } from "../lib/nodeApprovals";
import { taskKeys } from "../lib/tasks";
import type { NodeDevice, NodeOrder, Task, User } from "../types";
import { useEvents } from "../lib/useEvents";

/**
 * El rail de Vibi.
 *
 * Los seis destinos nombran **lo que haces**, no el tipo de objeto que hay
 * dentro. El rail anterior era un inventario —Actividad, Proyectos, Skills,
 * Tools, Archivos— y gastaba dos de sus seis huecos en configuración del agente
 * mientras el trabajo vivo (lo que está pasando ahora, la conversación, la
 * malla) no tenía ninguno.
 *
 * - **Proyectos**: dónde vive cada cosa. Va el primero porque casi todo lo
 *   demás pasa dentro de uno: ahí están sus archivos, sus conversaciones
 *   guardadas y la carpeta que recibe sus encargos. Estuvo dentro del Taller
 *   mientras solo era una lista de repos clonados; desde que guarda material y
 *   conversaciones ya no es configuración que se toca de vez en cuando.
 * - **Ahora**: el turno en marcha, entero y en un solo sitio.
 * - **Hilo**: la conversación. Voz, PWA y Telegram ya escriben en el mismo.
 * - **Encargos**: lo agéntico, lo que sobrevive al turno. Era la columna
 *   derecha de 352 px que estaba siempre puesta aunque no hubiera nada.
 * - **Equipos**: la malla, que era mil líneas de servidor y cuatro caracteres
 *   de pantalla.
 * - **Taller**: skills, herramientas y archivos. Materiales y configuración,
 *   fuera del camino diario pero a un clic.
 */

const DESTINOS = [
  { to: "/proyectos", label: "Proyectos", icon: FolderKanban },
  { to: "/", label: "Ahora", icon: Clock3, end: true },
  { to: "/hilo", label: "Hilo", icon: MessageSquare },
  { to: "/encargos", label: "Encargos", icon: SquareStack, cuenta: "encargos" },
  { to: "/equipos", label: "Equipos", icon: Monitor, cuenta: "equipos" },
  { to: "/taller", label: "Taller", icon: Wrench },
] as const;

export function AppShell() {
  useEvents();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  useEffect(() => {
    const clearPrivateCache = () => queryClient.clear();
    window.addEventListener("vibi:unauthorized", clearPrivateCache);
    return () =>
      window.removeEventListener("vibi:unauthorized", clearPrivateCache);
  }, [queryClient]);

  const user = useQuery({
    queryKey: ["me"],
    queryFn: () => apiFetch<User>("/api/yo"),
  });

  // Las dos cifras del rail. Se piden aquí y no en sus páginas porque el rail
  // se ve desde cualquier sitio: son justo los números que evitan tener que
  // entrar a mirar si hay algo.
  const tareas = useQuery<Task[]>({
    queryKey: taskKeys.list("", ""),
    queryFn: () => apiFetch<Task[]>("/api/tareas?limite=100"),
  });
  const nodos = useQuery<NodeDevice[]>({ queryKey: nodosKey, queryFn: fetchNodos });
  const aprobaciones = useQuery<NodeOrder[]>({
    queryKey: nodeApprovalsKey,
    queryFn: fetchNodeApprovals,
  });

  const vivas = (tareas.data ?? []).filter(
    (t) =>
      t.estado === "pendiente" ||
      t.estado === "planificando" ||
      t.estado === "ejecutando" ||
      t.estado === "esperando_aprobacion",
  ).length;
  const conectados = (nodos.data ?? []).filter((n) => n.conectado).length;
  const pendientes = aprobaciones.data?.length ?? 0;

  const cuentas: Record<string, string> = {
    encargos: vivas ? String(vivas) : "",
    equipos: nodos.data?.length ? `${conectados}/${nodos.data.length}` : "",
  };

  const logout = () => {
    clearToken();
    queryClient.clear();
    navigate("/login", { replace: true });
  };

  return (
    <div className="console-shell">
      <aside className="console-rail">
        <div className="rail-brand" aria-label="Aplicación local de Vibi">
          <strong>VIBI // LOCAL</strong>
          <span><i aria-hidden="true" /> SISTEMA EN LÍNEA</span>
        </div>

        <RailFace />

        <nav className="rail-nav" aria-label="Vibi">
          {DESTINOS.map(({ to, label, icon: Icon, ...resto }) => {
            const cuenta = "cuenta" in resto ? cuentas[resto.cuenta] : "";
            return (
              <NavLink
                key={to}
                to={to}
                end={"end" in resto ? resto.end : false}
                className="rail-link"
              >
                <Icon size={19} strokeWidth={1.7} />
                <span>{label}</span>
                {cuenta && <span className="rail-cuenta">{cuenta}</span>}
              </NavLink>
            );
          })}
        </nav>

        {/* Lo único que no puede esperar tiene sitio fijo en el rail: se ve
            desde cualquier página y lleva a donde se decide. */}
        {pendientes > 0 && (
          <NavLink to="/" end className="rail-permiso">
            {pendientes === 1
              ? "1 orden espera tu permiso"
              : `${pendientes} órdenes esperan permiso`}
          </NavLink>
        )}

        <div className="rail-user">
          <span className="user-avatar">
            {user.data?.nombre.slice(0, 1).toUpperCase() ?? "·"}
          </span>
          <span className="user-name">{user.data?.nombre ?? "Conectando"}</span>
          <NavLink to="/configuracion" className="icon-button" aria-label="Ajustes">
            <Settings2 size={17} />
          </NavLink>
          <button onClick={logout} className="icon-button" aria-label="Cerrar sesión">
            <LogOut size={17} />
          </button>
        </div>
      </aside>

      {/* Sin columna fija a la derecha: cada página monta la suya si la
          necesita. La bandeja ocupaba 352 px pasara lo que pasara. */}
      <main className="console-center">
        <Outlet />
      </main>
    </div>
  );
}
