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
    // Bind on all interfaces so a Pinggy tunnel (`ssh -p 443 -R0:localhost:5173
    // a.pinggy.io`) can reach the dev server. Harmless locally; it only means
    // the port is reachable from the machine's LAN address as well as
    // 127.0.0.1.
    host: true,
    // A tunnel arrives with a Host header Vite does not recognise and would
    // otherwise reject as a DNS-rebinding attempt. Pinggy hands out a fresh
    // subdomain per session, so the suffixes are allowlisted rather than the
    // hostnames.
    allowedHosts: ['.pinggy.link', '.pinggy.io', '.https://bpkkppxaec.a.pinggy.link '],
    proxy: {
      '/api': {
        // A local backend, because the project is no longer hosted. This used
        // to default to the Railway deployment, which meant `npm run dev`
        // talked to a machine running its own scheduler against the shared Neon
        // database — and if a local uvicorn was also up, both schedulers built
        // plans for the same incidents and every model call was paid twice.
        // Set VITE_API_TARGET to point somewhere else when you need to.
        target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000',
        // Rewrite the Host header to match the target, so the backend sees a
        // request that looks like it was addressed to it directly.
        changeOrigin: true,
      }
    }
  }
})