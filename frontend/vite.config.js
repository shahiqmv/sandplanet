import { resolve } from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Production build serves under Django/WhiteNoise at /static/ (index.html
// then references /static/assets/*, matching STATICFILES_DIRS). The dev
// server stays at / so localhost:5173 works unchanged.
//
// Two entry points share one build: the desktop SPA (index.html) and Planet
// Mobile, the installable PWA (m.html → served by Django at /m/).
export default defineConfig(({ mode }) => ({
  base: mode === "production" ? "/static/" : "/",
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        mobile: resolve(__dirname, "m.html"),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/admin": "http://127.0.0.1:8000",
      "/media": "http://127.0.0.1:8000",
    },
  },
}));
