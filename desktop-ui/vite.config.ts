import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    host: "0.0.0.0",
    port: 1420,
    strictPort: true,
    allowedHosts: true,
    proxy: {
      "/ws/myhands": {
        target: "ws://127.0.0.1:8795",
        ws: true,
      },
      "/api/myhands": {
        target: "http://127.0.0.1:8795",
      },
    },
  },
  envPrefix: ["VITE_", "TAURI_ENV_*"],
  build: {
    target: "es2021",
    sourcemap: true,
  },
});
