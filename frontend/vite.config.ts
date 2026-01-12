import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'happy-dom',
    setupFiles: './src/test/setup.ts',
    exclude: ['**/e2e/**', '**/node_modules/**'],
  },
  server: {
    port: 3000,
    host: true, // Listen on all addresses
    proxy: {
      // SSE/events endpoint - needs special handling for streaming
      '/v1/documents': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
        configure: (proxy) => {
          // Disable response body buffering for SSE
          proxy.on('proxyRes', (proxyRes) => {
            // Prevent buffering for text/event-stream
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache'
              proxyRes.headers['connection'] = 'keep-alive'
            }
          })
          // Handle proxy errors gracefully
          proxy.on('error', (err, _req, res) => {
            console.error('Proxy error:', err)
            if (res && 'writeHead' in res) {
              res.writeHead(502, { 'Content-Type': 'text/plain' })
              res.end('Proxy error')
            }
          })
        },
      },
      // SSE endpoint for chat query - needs special handling
      '/v1': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (_, req) => {
            // Log proxy requests to verify matching
            if (req.url?.includes('/query')) {
              console.log('Proxying Chat Request (via /v1):', req.url);
            }
          });
          proxy.on('proxyRes', (proxyRes, req) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              console.log('Disabling buffering for SSE (main /v1 rule):', req.url);
              proxyRes.headers['cache-control'] = 'no-cache'
              proxyRes.headers['connection'] = 'keep-alive'
            }
          })
        },
      },
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})

