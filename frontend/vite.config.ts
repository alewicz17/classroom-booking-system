import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In Docker Compose the API is reachable as http://api:8000; locally on localhost.
const apiUrl = process.env.API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": { target: apiUrl, rewrite: (path) => path.replace(/^\/api/, "") },
    },
  },
});
