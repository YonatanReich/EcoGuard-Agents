/// <reference types="vite/client" />

declare module '@fontsource/plus-jakarta-sans'

interface ImportMetaEnv {
  readonly VITE_MAPTILER_KEY: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
