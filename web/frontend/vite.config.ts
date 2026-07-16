import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // Prevent Node proxy from buffering SSE token streams.
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, _req, res) => {
            const ct = proxyRes.headers['content-type'] || ''
            if (String(ct).includes('text/event-stream')) {
              res.setHeader('Cache-Control', 'no-cache, no-transform')
              res.setHeader('X-Accel-Buffering', 'no')
              // @ts-expect-error Node ServerResponse flushHeaders
              if (typeof res.flushHeaders === 'function') res.flushHeaders()
            }
          })
        },
      },
    },
  },
  build: {
    outDir: '../../src/rimbook/web/backend/static',
    emptyOutDir: true,
  },
})
