import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import {
  FolderGit2,
  Inbox,
  LogOut,
  MessageCircle,
  ScanFace,
} from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { apiFetch } from "../lib/api";
import { clearToken } from "../lib/auth";
import type { User } from "../types";
import { useEvents } from "../lib/useEvents";

const navigation = [
  { to: "/", label: "Bandeja", icon: Inbox, end: true },
  { to: "/chat", label: "Chat", icon: MessageCircle },
  { to: "/proyectos", label: "Proyectos", icon: FolderGit2 },
  { to: "/cara", label: "Cara", icon: ScanFace },
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
    <div className="app-shell">
      <aside className="desktop-rail">
        <NavLink to="/" className="brand" aria-label="Morgana, bandeja">
          <span className="brand-mark">✦</span>
          <span>Morgana</span>
        </NavLink>
        <nav className="rail-links" aria-label="Navegación principal">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className="nav-link">
              <Icon size={19} strokeWidth={1.7} />
              <span>{label}</span>
            </NavLink>
          ))}
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

      <div className="mobile-brand">
        <NavLink to="/" className="brand">
          <span className="brand-mark">✦</span>
          <span>Morgana</span>
        </NavLink>
        <button onClick={logout} className="icon-button" aria-label="Cerrar sesión">
          <LogOut size={18} />
        </button>
      </div>

      <main className="app-content">
        <Outlet />
      </main>

      <nav className="mobile-nav" aria-label="Navegación principal">
        {navigation.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className="mobile-nav-link">
            <Icon size={20} strokeWidth={1.7} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
