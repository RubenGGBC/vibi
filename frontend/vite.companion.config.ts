import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "dist-companion",
    emptyOutDir: true,
    assetsInlineLimit: (filePath) =>
      filePath.endsWith(".woff2") ? false : undefined,
    rollupOptions: {
      // Las dos entradas en el mismo sitio, y esto es lo que convierte a Vibi
      // en una aplicación: `companion.html` es la cara flotante y `index.html`
      // es la interfaz entera —chat, archivos, ajustes—. Mientras solo se
      // empaquetaba la primera, la app no tenía ventana propia y esa interfaz
      // solo existía en el navegador, que es justo lo que no se quiere.
      input: {
        companion: fileURLToPath(new URL("./companion.html", import.meta.url)),
        principal: fileURLToPath(new URL("./index.html", import.meta.url)),
      },
    },
  },
  server: {
    port: 1420,
    strictPort: true,
  },
});

