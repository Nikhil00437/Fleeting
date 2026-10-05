/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:7425", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    // Default stays `node` on purpose: most tests here render through
    // renderToStaticMarkup, which needs no DOM and is much faster without one.
    // Behaviour tests (effects, events, error boundaries) opt in per file with
    // a `@vitest-environment jsdom` docblock — see *.dom.test.tsx.
    environment: "node",
  },
});
