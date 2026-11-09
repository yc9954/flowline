import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));

// Board dev server: 5173, proxies /api to the Flowline API on 8787.
// Fixtures live one directory up (../fixtures) and are imported by the app as the offline fallback.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: process.env.FLOWLINE_API ?? 'http://localhost:8787', changeOrigin: true },
    },
    fs: { allow: [resolve(here, '..')] },
  },
  build: { outDir: 'dist', emptyOutDir: true },
});
