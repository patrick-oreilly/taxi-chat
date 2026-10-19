import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the page runs on Vite and the API on FastAPI (port 8000).
export default defineConfig({
  plugins: [react()],
  // A local app: deck.gl and MapLibre are big and there is no network to save.
  build: { chunkSizeWarningLimit: 1500 },
  worker: { format: 'es' },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
