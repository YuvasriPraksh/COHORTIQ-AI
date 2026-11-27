/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// In development, API requests go through this server to the FastAPI backend,
// so the browser only talks to one origin. Set VITE_API_PROXY_TARGET to point
// at a backend that is not on http://127.0.0.1:8000.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": { target: env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000", changeOrigin: true },
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
      css: false,
    },
  };
});
