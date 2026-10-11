import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Production builds get a Content-Security-Policy <meta> tag.
 *
 * GitHub Pages cannot send response headers, so the meta tag is the only way
 * to ship a CSP. It is built from the same env vars the app uses, so the
 * allowed API and Supabase origins always match the build. Dev builds skip it:
 * Vite's dev server relies on inline scripts and a websocket for hot reload.
 *
 * (frame-ancestors is ignored in a meta tag; the frame check in main.jsx
 * covers clickjacking instead.)
 */
function contentSecurityPolicy(env) {
  const origin = (value) => {
    try {
      return new URL(value).origin
    } catch {
      return null
    }
  }
  const api = origin(env.VITE_API_URL)
  const supabase = origin(env.VITE_SUPABASE_URL)
  // No wss: the app does not use Supabase realtime.
  const connect = ["'self'", api, supabase].filter(Boolean)

  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    `connect-src ${connect.join(' ')}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    // Skipped for a local http API, which it would otherwise rewrite to https.
    api?.startsWith('https:') ? 'upgrade-insecure-requests' : null,
  ]
    .filter(Boolean)
    .join('; ')
}

/** Refuse to produce a production bundle that cannot work, or would leak. */
function checkProductionEnv(env) {
  const missing = ['VITE_API_URL', 'VITE_SUPABASE_URL', 'VITE_SUPABASE_ANON_KEY'].filter(
    (name) => !env[name],
  )
  if (missing.length) {
    throw new Error(`Missing build settings: ${missing.join(', ')}. See frontend/.env.example.`)
  }
  const api = new URL(env.VITE_API_URL)
  const local = ['localhost', '127.0.0.1'].includes(api.hostname)
  if (api.protocol !== 'https:' && !local) {
    throw new Error(`VITE_API_URL must use https:// in production (got ${env.VITE_API_URL}).`)
  }
  // The service-role key bypasses Row Level Security entirely. If it is ever
  // pasted here by mistake, it would be published inside the bundle.
  try {
    const payload = JSON.parse(
      Buffer.from(env.VITE_SUPABASE_ANON_KEY.split('.')[1], 'base64url').toString(),
    )
    if (payload.role && payload.role !== 'anon') {
      throw new Error(`VITE_SUPABASE_ANON_KEY has role "${payload.role}"; only the anon key is safe to publish.`)
    }
  } catch (err) {
    if (err.message.includes('only the anon key')) throw err
    // New-style publishable keys (sb_publishable_...) are not JWTs; nothing to check.
  }
}

function securityPlugin(env) {
  return {
    name: 'screenai-security',
    apply: 'build',
    buildStart() {
      checkProductionEnv(env)
    },
    transformIndexHtml() {
      return [
        {
          tag: 'meta',
          attrs: { 'http-equiv': 'Content-Security-Policy', content: contentSecurityPolicy(env) },
          injectTo: 'head-prepend',
        },
      ]
    },
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  return {
    plugins: [react(), securityPlugin(env)],
    build: {
      // No source maps in the published bundle.
      sourcemap: false,
    },
  }
})
