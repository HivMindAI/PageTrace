import { defineConfig } from "vite";

export default defineConfig({
  build: {
    emptyOutDir: true,
    outDir: "../src/pagetrace/web/dist",
  },
  server: {
    proxy: {
      "/healthz": "http://127.0.0.1:8765",
      "/readyz": "http://127.0.0.1:8765",
      "/v1": "http://127.0.0.1:8765",
    },
  },
});
