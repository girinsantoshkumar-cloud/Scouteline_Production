import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Locally this defaults to localhost:8000. Inside docker-compose it's set to
// http://backend:8000 so the frontend container can reach the backend
// container by its service name.
const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  test: { environment: 'jsdom', include: ['src/**/*.test.{ts,tsx}'] },
  server: {
    host: true,
    port: 5173,
    proxy: { '/api': { target: backendUrl, changeOrigin: true } },
  },
})
