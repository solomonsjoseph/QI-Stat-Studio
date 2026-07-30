import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
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
