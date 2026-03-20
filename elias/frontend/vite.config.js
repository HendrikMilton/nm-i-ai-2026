import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'

const logsDir = path.resolve(__dirname, '..', 'logs')

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'serve-logs',
      configureServer(server) {
        // Serve the round index (lightweight, polled every 15s)
        server.middlewares.use('/api/logs/index', (_req, res) => {
          const file = path.join(logsDir, 'index.json')
          res.setHeader('Content-Type', 'application/json')
          if (fs.existsSync(file)) {
            res.end(fs.readFileSync(file, 'utf-8'))
          } else {
            res.end('{"rounds":[]}')
          }
        })

        // Serve individual round files (fetched on demand)
        server.middlewares.use('/api/logs/rounds/', (req, res) => {
          const roundId = req.url.replace(/^\//, '').replace(/\.json$/, '')
          if (!roundId || roundId.includes('/') || roundId.includes('..')) {
            res.statusCode = 400
            res.end('{"error":"invalid round id"}')
            return
          }
          const file = path.join(logsDir, 'rounds', `${roundId}.json`)
          res.setHeader('Content-Type', 'application/json')
          if (fs.existsSync(file)) {
            res.end(fs.readFileSync(file, 'utf-8'))
          } else {
            res.statusCode = 404
            res.end('{"error":"round not found"}')
          }
        })
      },
    },
  ],
  server: {
    proxy: {
      '/astar-island': {
        target: 'https://api.ainm.no',
        changeOrigin: true,
        secure: true,
      },
    },
  },
})
