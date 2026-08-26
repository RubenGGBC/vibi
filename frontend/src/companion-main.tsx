import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { CompanionApp } from "./components/CompanionApp";
import { CompanionPanel } from "./components/CompanionPanel";
import { ProcesoMotor } from "./components/ProcesoMotor";
import { applyCompanionSession } from "./lib/companionApi";
import "./styles/companion.css";
import "./styles/cara.css";

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
const cual = (() => {
  try {
    return getCurrentWindow().label;
  } catch {
    // `npm run dev` abre esto en un navegador normal, donde no hay ventana de
    // Tauri a la que preguntar. El hash es el respaldo para poder trabajar.
    return window.location.hash.replace("#", "") || "companion";
  }
})();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      {cual === "panel" ? (
        <CompanionPanel />
      ) : cual === "proceso" ? (
        <ProcesoMotor />
      ) : (
        <CompanionApp />
      )}
    </QueryClientProvider>
  </StrictMode>,
);
