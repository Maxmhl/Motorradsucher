import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Im Dev-Modus laeuft Vite auf 5173 und reicht /api und /ws an FastAPI weiter.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
