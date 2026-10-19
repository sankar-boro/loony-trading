import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5163,
    proxy: {
      // xfwd: pass the browser's address on, so the backend can tell a remote
      // visitor from this machine even through the dev proxy
      '/api': { target: 'http://localhost:8000', changeOrigin: true, xfwd: true },
      '/ws':  { target: 'ws://localhost:8000',   ws: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
