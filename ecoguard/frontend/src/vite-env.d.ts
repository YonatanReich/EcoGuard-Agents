/**
 * Ambient TypeScript declarations for the frontend.
 *
 * Responsible for telling the compiler about things that exist at runtime but
 * have no types of their own: Vite's client globals, the untyped font
 * package, and this project's environment variables.
 *
 * Nothing here emits code — it is types only.
 */

/// <reference types="vite/client" />

// The font package ships CSS with no type declarations, so importing it for
// its side effect would otherwise be a compile error.
declare module '@fontsource/plus-jakarta-sans'

/**
 * Environment variables available through import.meta.env.
 *
 * Only VITE_-prefixed variables are exposed to client code by Vite. Declaring
 * them here makes import.meta.env.VITE_MAPBOX_KEY type-checked and
 * autocompleted rather than `any`.
 *
 * Set these in frontend/.env, which is gitignored.
 */
interface ImportMetaEnv {
  /** Mapbox public access token (pk.*) used by MapView to load the basemap. */
  readonly VITE_MAPBOX_KEY: string

  /** MapTiler key. Unused since the Mapbox migration; kept for rollback. */
  readonly VITE_MAPTILER_KEY?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
