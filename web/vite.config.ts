import { defineConfig } from 'vite';

// public/ (repo root) is the data pipeline's published output; serve it as-is.
export default defineConfig({
  publicDir: '../public',
  build: { outDir: 'dist', emptyOutDir: true, target: 'es2020' },
  server: { port: 5173 },
});
