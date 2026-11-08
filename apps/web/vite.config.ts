import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Docker Desktop file sharing does not reliably forward native file events
    // from Windows/macOS hosts into the Linux container.
    watch: {
      usePolling: process.env.VITE_USE_POLLING !== "false",
      interval: 500,
    },
  },
});
