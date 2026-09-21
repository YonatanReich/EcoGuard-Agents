/**
 * Frontend entry point.
 *
 * Responsible for bootstrapping React onto the #root element in index.html
 * and installing the two providers the whole app depends on. Nothing else
 * belongs here — application structure starts in App.tsx.
 *
 * The font and global stylesheet are imported here rather than in a
 * component so they are bundled once and applied before first paint.
 */

import '@fontsource/plus-jakarta-sans'
// The package's default import is weight 400 only. Without the real heavier
// cuts the browser fakes bold by smearing the 400 glyphs, which crowds words
// together, so load every weight the stylesheets use.
import '@fontsource/plus-jakarta-sans/500.css'
import '@fontsource/plus-jakarta-sans/600.css'
import '@fontsource/plus-jakarta-sans/700.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'

// The non-null assertion on #root is safe: the element is hardcoded in
// index.html, so if it were missing the app could not run at all.
createRoot(document.getElementById('root')!).render(
  // BrowserRouter gives the app routing capabilities; StrictMode surfaces
  // unsafe patterns and double-invokes effects in dev to expose side effects.
  // StrictMode is a dev-only behaviour and has no effect in a production build.
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
