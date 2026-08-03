import path from "path"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    allowedHosts: true,
    host: true,
    cors: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          // Split the WebGL stack into its own vendor chunk so it is
          // cached independently and loaded lazily with the scene.
          three: ["three"],
          r3f: [
            "@react-three/fiber",
            "@react-three/drei",
            "@react-three/postprocessing",
          ],
        },
      },
    },
  },
})