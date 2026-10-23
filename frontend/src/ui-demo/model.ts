import { useEffect, useState } from "react";

export type Task = { id: string; title: string; project: string; status: "En curso" | "Pendiente" | "Completado"; progress: number };
export type Project = { id: string; name: string; description: string; tag: string };
export type Skill = { id: string; name: string; description: string; instructions: string; enabled: boolean };
export type DemoFile = { id: string; name: string; content: string; size: string };
export type Message = { id: string; role: "user" | "assistant"; text: string; attachment?: string };
export type Team = { id: string; name: string; members: string; observation: boolean };
export type Device = { id: string; name: string; system: string; online: boolean };
export type Store = {
  tasks: Task[]; projects: Project[]; skills: Skill[]; files: DemoFile[]; messages: Message[];
  teams: Team[]; devices: Device[]; activity: string[];
  settings: { voice: boolean; wake: boolean; notifications: boolean; engine: string; model: string; name: string; preference: string; };
};
export const initialStore: Store = {
  tasks: [
    { id: "task-1", title: "Preparar el resumen de investigación", project: "Trabajo de fin de grado", status: "En curso", progress: 68 },
    { id: "task-2", title: "Organizar las referencias", project: "Trabajo de fin de grado", status: "Pendiente", progress: 0 },
    { id: "task-3", title: "Revisar los componentes de la interfaz", project: "Vibi", status: "Completado", progress: 100 },
  ],
  projects: [
    { id: "project-1", name: "Trabajo de fin de grado", description: "Ideas, investigación y un poco de orden.", tag: "Investigación" },
    { id: "project-2", name: "Vibi", description: "Un pequeño compañero. Muchas posibilidades.", tag: "Desarrollo" },
    { id: "project-3", name: "Espacio personal", description: "Todo lo que no necesita una carpeta más.", tag: "Personal" },
  ],
  skills: [
    { id: "skill-1", name: "Investigación", description: "Conecta fuentes y prepara resúmenes con contexto.", instructions: "Compara las fuentes, cita su origen y presenta una síntesis breve en español.", enabled: true },
    { id: "skill-2", name: "Compañero de código", description: "Revisa, construye y cuida los pequeños detalles.", instructions: "Revisa el contexto del proyecto y verifica los cambios antes de terminar.", enabled: true },
    { id: "skill-3", name: "Ordenar archivos", description: "Cada documento, en su sitio.", instructions: "Agrupa por proyecto y conserva los nombres originales.", enabled: false },
  ],
  files: [
    { id: "file-1", name: "Notas de investigación.md", content: "# Notas de investigación\n\nObjetivo: explorar cómo los asistentes locales ayudan a organizar el trabajo.\n\n## Próximos pasos\n- Comparar las fuentes\n- Preparar una primera síntesis", size: "1.2 KB" },
    { id: "file-2", name: "Referencias.txt", content: "Referencias de ejemplo de la demo de Vibi.\nAñade aquí tus fuentes.", size: "0.4 KB" },
  ],
  messages: [{ id: "message-1", role: "assistant", text: "Todo listo por aquí. Estoy preparando tu resumen de investigación y tengo tus proyectos a mano. ¿Qué hacemos ahora?" }],
  teams: [{ id: "team-1", name: "Equipo de investigación", members: "Rubén, Ana, Pablo", observation: false }],
  devices: [{ id: "device-1", name: "MacBook de Rubén", system: "macOS · Este dispositivo", online: true }, { id: "device-2", name: "PC de casa", system: "Windows · Nodo remoto", online: true }, { id: "device-3", name: "Mi móvil", system: "PWA · Última conexión ayer", online: false }],
  activity: ["Vibi está preparando el resumen de investigación", "Se han encontrado 8 referencias en tu proyecto", "Revisión de componentes completada", "MacBook de Rubén se ha conectado"],
  settings: { voice: true, wake: false, notifications: true, engine: "Claude Code", model: "Automático", name: "Rubén", preference: "Respuestas claras y breves, en español." },
};

export function useDemoStore() {
  const [store, setStore] = useState<Store>(() => {
    try {
      const raw = localStorage.getItem("vibi-ui-demo-v1");
      if (raw) {
        const saved = JSON.parse(raw);
        if (Object.keys(initialStore).every((key) => key in saved)) return saved;
      }
    } catch { /* Use sample data if storage is unavailable. */ }
    return initialStore;
  });
  useEffect(() => { try { localStorage.setItem("vibi-ui-demo-v1", JSON.stringify(store)); } catch { /* In-memory demo still works. */ } }, [store]);
  return [store, setStore] as const;
}

export function id() { return crypto.randomUUID(); }
export function download(name: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url; link.download = name; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
