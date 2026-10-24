import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'

const { version } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'))

export default defineConfig({
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify(version) },
  server: {
    // Permit Cloudflare Quick Tunnels for temporary remote previews while
    // retaining Vite's host-header protection for every other hostname.
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${process.env.API_PORT || 8000}`,
        changeOrigin: true,
        rewrite: path => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    setupFiles: './src/test/setup.js',
    environment: 'jsdom',
    exclude: ['node_modules/**', 'dist/**', 'e2e/**'],
  },
})
