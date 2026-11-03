import { cp } from "node:fs/promises";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// pdf.js loads these at run time, so they ship in the build instead of coming from a CDN.
const pdfjsAssets = () => ({
  name: "pdfjs-assets",
  apply: "build" as const,
  async closeBundle() {
    for (const folder of ["cmaps", "standard_fonts", "wasm"]) {
      await cp(`node_modules/pdfjs-dist/${folder}`, `dist/pdfjs/${folder}`, { recursive: true });
    }
  },
});

// MapLibre starts its worker from a URL, so the worker file is copied beside the build.
const maplibreWorker = () => ({
  name: "maplibre-worker",
  apply: "build" as const,
  async closeBundle() {
    await cp("node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs",
      "dist/maplibre/maplibre-gl-worker.mjs");
  },
});

export default defineConfig({
  plugins: [react(), pdfjsAssets(), maplibreWorker()],
  server: { proxy: { "/api": "http://127.0.0.1:8080" } },
  test: { environment: "jsdom", globals: true, setupFiles: "./src/test-setup.ts" },
});
