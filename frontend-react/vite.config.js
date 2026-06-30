import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: '/biopsy-prediction/',
  server: {
    port: parseInt(process.env.PORT ?? '5173'),
    proxy: {
      '/predict': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
