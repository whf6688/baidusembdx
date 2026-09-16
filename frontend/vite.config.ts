import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // UI edits hot-reload through Vite while API calls pass through the running local gateway.
  // A frontend Docker rebuild is only needed for final release verification.
  const apiProxyTarget = loadEnv(mode, '.', 'VITE_').VITE_API_PROXY_TARGET || 'http://localhost:8000'
  return {
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom'],
          fluent: ['@fluentui/react-components', '@fluentui/react-icons'],
        },
      },
    },
  },
  server: {
    port: 8280,
    strictPort: true,
    proxy: { '/api': apiProxyTarget },
  },
  }
})
