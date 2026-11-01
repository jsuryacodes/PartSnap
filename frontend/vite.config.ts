import basicSsl from '@vitejs/plugin-basic-ssl'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// HTTPS + LAN so a phone can use the camera and motion sensors. /api proxies to the local FastAPI.
export default defineConfig({
  plugins: [react(), basicSsl()],
  server: {
    host: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', rewrite: (p) => p.replace(/^\/api/, '') } },
  },
})
