import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/admin/",
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/admin": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
});