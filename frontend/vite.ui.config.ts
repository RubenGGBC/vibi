import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist-ui",
    assetsInlineLimit: (path) => path.endsWith(".woff2") ? false : undefined,
    rollupOptions: { input: fileURLToPath(new URL("./ui-demo.html", import.meta.url)) },
  },
});
