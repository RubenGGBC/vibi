import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist-fox",
    rollupOptions: { input: fileURLToPath(new URL("./companion-fox.html", import.meta.url)) },
  },
});
