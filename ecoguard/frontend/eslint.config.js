/**
 * ESLint configuration (flat config format).
 *
 * Responsible for the lint rules applied to the frontend TypeScript sources.
 * Run with `npm run lint` from the frontend directory.
 *
 * Composed from four rule sets: baseline JavaScript, TypeScript, React Hooks
 * (catches dependency-array and conditional-hook mistakes), and React Refresh
 * (warns about exports that would break fast refresh in dev).
 */

import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  // Build output is generated, never hand-edited — don't lint it.
  globalIgnores(['dist']),
  {
    // Source is TypeScript only; plain .js config files are not linted.
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
  },
])
