import "@fontsource-variable/newsreader";
import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, HashRouter } from "react-router-dom";

import { App } from "./App";
import { setApiBase } from "./lib/api";
import { baseDeLaApi, corriendoEnLaApp } from "./lib/entorno";
import "./styles.css";
import "./styles/console.css";
import "./styles/cara.css";

// Lo primero de todo, antes de montar nada: si la interfaz no sabe dónde está
// el core, la primera petición sale hacia `tauri://localhost` y la ventana se
// queda en negro sin un solo error a la vista.
setApiBase(baseDeLaApi());

// Y por rutas, según dónde corra. En el navegador el core sirve la interfaz
// para cualquier ruta, así que las direcciones limpias funcionan. Dentro de la
// aplicación no hay servidor: `/ajustes` se buscaría como un archivo que no
// existe y la ventana se quedaría en blanco al primer clic.
const Rutas = corriendoEnLaApp() ? HashRouter : BrowserRouter;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false },
    mutations: { retry: 0 },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <Rutas>
        <App />
      </Rutas>
    </QueryClientProvider>
  </StrictMode>,
);
