import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { ConsolePage } from "./pages/ConsolePage";
import { FilesPage } from "./pages/FilesPage";
import { LoginPage } from "./pages/LoginPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { TaskDetailPage } from "./pages/TaskDetailPage";
import { ToolsPage } from "./pages/ToolsPage";
import { SettingsPage } from "./pages/SettingsPage";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route index element={<ConsolePage />} />
          <Route path="tareas/:id" element={<TaskDetailPage />} />
          <Route path="proyectos" element={<ProjectsPage />} />
          <Route path="archivos" element={<FilesPage />} />
          <Route path="herramientas" element={<ToolsPage />} />
          <Route path="configuracion" element={<SettingsPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
