import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Activity, Files, FolderGit2, LogOut, Settings, Sparkles, Wrench } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { AprobacionesPanel } from "./AprobacionesPanel";
import { BandejaPanel } from "./BandejaPanel";
import { apiFetch } from "../lib/api";
import { clearToken } from "../lib/auth";
import type { User } from "../types";
import { useEvents } from "../lib/useEvents";

const workspace = [
  { to: "/actividad", label: "Actividad", icon: Activity },
  { to: "/proyectos", label: "Proyectos", icon: FolderGit2 },
  { to: "/skills", label: "Skills", icon: Sparkles },
  { to: "/herramientas", label: "Tools", icon: Wrench },
  { to: "/archivos", label: "Archivos", icon: Files },
];

export function AppShell() {
  useEvents();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  useEffect(() => {
    const clearPrivateCache = () => queryClient.clear();
    window.addEventListener("morgana:unauthorized", clearPrivateCache);
    return () =>
      window.removeEventListener("morgana:unauthorized", clearPrivateCache);
  }, [queryClient]);
  const user = useQuery({
    queryKey: ["me"],
    queryFn: () => apiFetch<User>("/api/yo"),
  });
  const logout = () => {
    clearToken();
    queryClient.clear();
    navigate("/login", { replace: true });
  };

  return (
    <div className="console-shell">
      <aside className="console-rail">
        <NavLink to="/" className="brand" aria-label="Morgana, consola">
          <span className="brand-mark">✦</span>
          <span>Morgana</span>
        </NavLink>
        <nav className="rail-nav" aria-label="Workspace">
          {workspace.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className="rail-link">
              <Icon size={19} strokeWidth={1.7} />
              <span>{label}</span>
            </NavLink>
          ))}
          <NavLink to="/configuracion" className="rail-link">
            <Settings size={19} strokeWidth={1.7} />
            <span>Ajustes</span>
          </NavLink>
        </nav>
        <div className="rail-user">
          <span className="user-avatar">
            {user.data?.nombre.slice(0, 1).toUpperCase() ?? "·"}
          </span>
          <span className="user-name">{user.data?.nombre ?? "Conectando"}</span>
          <button onClick={logout} className="icon-button" aria-label="Cerrar sesión">
            <LogOut size={17} />
          </button>
        </div>
      </aside>

      <main className="console-center">
        <AprobacionesPanel />
        <Outlet />
      </main>

      <BandejaPanel />
    </div>
  );
}
