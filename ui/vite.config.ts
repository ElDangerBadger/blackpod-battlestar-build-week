/// <reference types="vitest/config" />

import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { defineConfig } from "vite";

export default defineConfig(({ mode }) => ({
  base: "./",
  // Archived mission packs must never be bundled with the normal product.
  build: { copyPublicDir: mode === "replay" },
  plugins: [react(), {
    name: "cabin-product-artwork",
    apply: "build",
    generateBundle() {
      if (mode !== "replay") this.emitFile({ type: "asset", fileName: "captains-cabin-template.png",
        source: readFileSync(new URL("./public/captains-cabin-template.png", import.meta.url)) });
    },
  }],
  server: { proxy: { "/live": { target: "http://127.0.0.1:5174", changeOrigin: true } } },
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
}));
