import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/ready': 'http://127.0.0.1:8080',
      '/workers': 'http://127.0.0.1:8080',
      '/resources': 'http://127.0.0.1:8080',
      '/metrics': 'http://127.0.0.1:8080',
      '/probes': 'http://127.0.0.1:8080',
      '/scenario': 'http://127.0.0.1:8080',
      '/start_test': 'http://127.0.0.1:8080',
      '/stop_test': 'http://127.0.0.1:8080',
      '/change_users': 'http://127.0.0.1:8080',
      '/create_resource': 'http://127.0.0.1:8080',
      '/ws': {
        target: 'http://127.0.0.1:8080',
        ws: true,
      },
    },
  },
})
