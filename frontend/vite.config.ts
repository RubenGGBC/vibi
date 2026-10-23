import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.png", "apple-touch-icon.png"],
      manifest: {
        name: "Vibi",
        short_name: "Vibi",
        description: "Planes, tareas y conversación para tus proyectos.",
        theme_color: "#0b0911",
        background_color: "#0b0911",
        display: "standalone",
        start_url: "/",
        scope: "/",
        lang: "es",
        icons: [
          {
            src: "/vibi-icon-192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "/vibi-icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "/vibi-icon-maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        navigateFallback: "/index.html",
        globPatterns: ["**/*.{js,css,html,svg,woff2}"],
        cleanupOutdatedCaches: true,
      },
    }),
  ],
  build: {
    // No incrustar las fuentes como data: URIs: la CSP del backend es
    // `font-src 'self'`, así que deben servirse como ficheros del propio origen.
    assetsInlineLimit: (filePath) =>
      filePath.endsWith(".woff2") ? false : undefined,
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        ws: true,
      },
    },
  },
});
