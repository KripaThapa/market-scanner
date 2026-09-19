import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
const backend = process.env.INTERNAL_BACKEND_URL || "http://127.0.0.1:8001";
export default defineConfig({
  plugins: [react()],
  server: { port: 3000, strictPort: true, proxy: { "/api/internal": backend } },
  preview: {
    port: 3000,
    strictPort: true,
    proxy: { "/api/internal": backend },
  },
});
