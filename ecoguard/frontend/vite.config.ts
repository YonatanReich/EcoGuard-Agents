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

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        // The hosted backend on Railway, so `npm run dev` works without a local
        // uvicorn. A local one would start a second scheduler against the
        // shared Neon database. Set VITE_API_TARGET=http://127.0.0.1:8000 to
        // point at a local backend anyway.
        target: process.env.VITE_API_TARGET ?? 'https://ecoguard-agents-production.up.railway.app',
        // Rewrite the Host header to match the target, so the backend sees a
        // request that looks like it was addressed to it directly.
        changeOrigin: true,
      }
    }
  }
})
