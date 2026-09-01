import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy /api -> backend FastAPI em :8000. Build: emite em dist/ (servido pelo FastAPI).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
