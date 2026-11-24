import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const files = process.env.VITE_FILES_PROXY || "http://127.0.0.1:8081";
const search = process.env.VITE_SEARCH_PROXY || "http://127.0.0.1:8080";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api/v1/search": { target: search, changeOrigin: true },
      "/api": { target: files, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    assetsDir: "assets",
  },
});
