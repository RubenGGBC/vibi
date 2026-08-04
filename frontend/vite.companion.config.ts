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
      input: fileURLToPath(new URL("./companion.html", import.meta.url)),
    },
  },
  server: {
    port: 1420,
    strictPort: true,
  },
});

