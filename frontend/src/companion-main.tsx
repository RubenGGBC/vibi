import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { CompanionApp } from "./components/CompanionApp";
import { CompanionPanel } from "./components/CompanionPanel";
import { applyCompanionSession } from "./lib/companionApi";
import "./styles/companion.css";

const client = new QueryClient({
  defaultOptions: {
    queries: {
      // El panel se abre y se cierra constantemente: sin esto haría una tanda
      // de peticiones cada vez que le echas un vistazo.
      staleTime: 15_000,
      retry: 1,
    },
  },
});

// Las credenciales del companion viven en su propio almacén; esto las pone
// donde el cliente HTTP compartido con la PWA sabe buscarlas.
applyCompanionSession();

// Las dos ventanas cargan el mismo bundle. La etiqueta que les puso Tauri es
// la señal fiable; el hash es el respaldo para `npm run dev`, donde se abre en
// un navegador normal y no hay ventana de Tauri a la que preguntar.
const esPanel = (() => {
  try {
    return getCurrentWindow().label === "panel";
  } catch {
    return window.location.hash === "#panel";
  }
})();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      {esPanel ? <CompanionPanel /> : <CompanionApp />}
    </QueryClientProvider>
  </StrictMode>,
);
