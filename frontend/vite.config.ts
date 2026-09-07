/**
 * Vite build and dev-server configuration.
 *
 * Responsible for two things: enabling React (JSX transform and fast refresh),
 * and proxying API calls to the FastAPI backend during development.
 *
 * The proxy is what lets the frontend fetch relative paths like
 * "/api/environmental-data". Vite forwards anything under /api to the Python
 * server on port 8000, so the browser sees a single origin and CORS never
 * comes into play in development.
 *
 * Docs: https://vite.dev/config/
 */

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import cesium from 'vite-plugin-cesium'

export default defineConfig({
  // EcoGuard keeps shared VITE_-prefixed frontend configuration in the
  // repository-level .env file rather than duplicating it under frontend/.
  envDir: '..',
  plugins: [react(), cesium({ rebuildCesium: true })],
  server: {
    proxy: {
      '/api': {
        // The Python backend, as started by `uvicorn backend.main:app`.
        target: 'http://127.0.0.1:8000',
        // Rewrite the Host header to match the target, so the backend sees a
        // request that looks like it was addressed to it directly.
        changeOrigin: true,
      }
    }
  }
})
