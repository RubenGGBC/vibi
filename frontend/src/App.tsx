import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { FacePage } from "./pages/FacePage";
import { ChatPage } from "./pages/ChatPage";
import { InboxPage } from "./pages/InboxPage";
import { LoginPage } from "./pages/LoginPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { TaskDetailPage } from "./pages/TaskDetailPage";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route index element={<InboxPage />} />
          <Route path="tareas/:id" element={<TaskDetailPage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="proyectos" element={<ProjectsPage />} />
          <Route path="cara" element={<FacePage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
