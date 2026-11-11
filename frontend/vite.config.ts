import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const apiUnavailable: Plugin = {
  name: "frontend-only-api-response",
  configureServer(server) {
    server.middlewares.use((request, response, next) => {
      const url = request.url ?? "";
      if (url !== "/api" && !url.startsWith("/api/")) return next();
      response.statusCode = 404;
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ detail: "This frontend-only development server does not include an API." }));
    });
  },
};

export default defineConfig({
  plugins: [react(), apiUnavailable],
  server: {
    port: 5173,
  },
  build: {
    outDir: "dist",
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL("./index.html", import.meta.url)),
        product: fileURLToPath(new URL("./product.html", import.meta.url)),
      },
    },
  },
});
