import viteReact from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
    tsconfigPaths: true,
  },
  plugins: [viteReact()],
  test: {
    environment: "happy-dom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api/connectors": {
        target: "http://127.0.0.1:8010",
        changeOrigin: true,
        ws: true,
      },
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
