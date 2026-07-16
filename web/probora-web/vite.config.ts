import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:5080',
      '/health': 'http://localhost:5080',
      '/hubs': {
        target: 'http://localhost:5080',
        ws: true,
      },
    },
  },
})
