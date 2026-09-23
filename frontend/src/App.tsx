import { Navigate, Route, Routes, useParams } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AhoraPage } from "./pages/AhoraPage";
import { ActivityPage } from "./pages/ActivityPage";
import { EncargosPage } from "./pages/EncargosPage";
import { EquiposPage } from "./pages/EquiposPage";
import { FilesPage } from "./pages/FilesPage";
import { HiloPage } from "./pages/HiloPage";
import { LoginPage } from "./pages/LoginPage";
import { ProjectDetailPage } from "./pages/ProjectDetailPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { TallerPage } from "./pages/TallerPage";
import { TaskDetailPage } from "./pages/TaskDetailPage";
import { ToolsPage } from "./pages/ToolsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SkillsPage } from "./pages/SkillsPage";
import { PerfilPage } from "./pages/PerfilPage";

/** `Navigate` no interpola parámetros, y el id del proyecto hay que conservarlo. */
function RedirigirAProyecto() {
  const { id = "" } = useParams();
  return <Navigate to={`/proyectos/${id}`} replace />;
}

/**
 * Seis destinos que nombran lo que haces, y un taller para el resto.
 *
 * Las rutas viejas siguen respondiendo con un redirect en vez de morir: hay
 * enlaces guardados por ahí —los eventos de actividad traen `enlace`, y el
 * companion abre la consola por URL— y romperlos para ahorrar cinco líneas
 * sería cobrárselo al usuario.
 */
export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route index element={<AhoraPage />} />
          <Route path="hilo" element={<HiloPage />} />
          <Route path="encargos" element={<EncargosPage />} />
          <Route path="tareas/:id" element={<TaskDetailPage />} />
          <Route path="equipos" element={<EquiposPage />} />
          <Route path="proyectos" element={<ProjectsPage />} />
          <Route path="proyectos/:id" element={<ProjectDetailPage />} />

          <Route path="taller" element={<TallerPage />}>
            <Route index element={<Navigate to="/taller/actividad" replace />} />
            <Route path="actividad" element={<ActivityPage />} />
            <Route path="perfil" element={<PerfilPage />} />
            <Route path="skills" element={<SkillsPage />} />
            <Route path="herramientas" element={<ToolsPage />} />
            <Route path="archivos" element={<FilesPage />} />
          </Route>

          <Route path="configuracion" element={<SettingsPage />} />

          {/* Las de antes. Proyectos hizo el viaje al revés que las demás: salió
              del taller al rail, así que el redirect que le queda mira hacia
              fuera y no hacia dentro. */}
          <Route path="perfil" element={<Navigate to="/taller/perfil" replace />} />
          <Route path="actividad" element={<Navigate to="/taller/actividad" replace />} />
          <Route path="taller/proyectos" element={<Navigate to="/proyectos" replace />} />
          <Route path="taller/proyectos/:id" element={<RedirigirAProyecto />} />
          <Route path="skills" element={<Navigate to="/taller/skills" replace />} />
          <Route path="herramientas" element={<Navigate to="/taller/herramientas" replace />} />
          <Route path="archivos" element={<Navigate to="/taller/archivos" replace />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
