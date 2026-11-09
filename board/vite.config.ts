import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { contractStub } from './scripts/contractStub';

const here = dirname(fileURLToPath(import.meta.url));
const api = process.env.FLOWLINE_API ?? 'http://localhost:8787';

// Board dev server: 5173 by default (`vite --port N` for another), proxies /api to the Flowline API (FLOWLINE_API).
// Fixtures live one directory up (../fixtures) and are imported by the app for ?fixtures=1 only.
// The contract stub answers the onboarding routes (boards, people, invites) in memory while the API lacks them.
export default defineConfig({
  plugins: [react(), ...(process.env.FLOWLINE_STUB === '0' ? [] : [contractStub(api)])],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: api, changeOrigin: true },
    },
    fs: { allow: [resolve(here, '..')] },
  },
  build: { outDir: 'dist', emptyOutDir: true },
});
