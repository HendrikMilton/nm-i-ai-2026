import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'

// Read from elias/logs — shared log directory for both pipelines
const logsDir = path.resolve(__dirname, '..', '..', 'elias', 'logs')

function serveJson(filePath, fallback) {
  return (_req, res) => {
    res.setHeader('Content-Type', 'application/json')
    if (fs.existsSync(filePath)) {
      res.end(fs.readFileSync(filePath, 'utf-8'))
    } else {
      res.end(fallback)
    }
  }
}

function serveJsonDir(dir) {
  return (req, res) => {
    const id = req.url.replace(/^\//, '').replace(/\.json$/, '')
    if (!id || id.includes('/') || id.includes('..')) {
      res.statusCode = 400
      res.end('{"error":"invalid id"}')
      return
    }
    const file = path.join(dir, `${id}.json`)
    res.setHeader('Content-Type', 'application/json')
    if (fs.existsSync(file)) {
      res.end(fs.readFileSync(file, 'utf-8'))
    } else {
      res.statusCode = 404
      res.end('{"error":"not found"}')
    }
  }
}

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'serve-logs',
      configureServer(server) {
        // Run logs
        server.middlewares.use('/api/logs/index',
          serveJson(path.join(logsDir, 'index.json'), '{"rounds":[]}'))
        server.middlewares.use('/api/logs/rounds/',
          serveJsonDir(path.join(logsDir, 'rounds')))

        // Offline backtest logs
        server.middlewares.use('/api/offline/index',
          serveJson(path.join(logsDir, 'offline', 'index.json'), '{"backtests":[]}'))
        server.middlewares.use('/api/offline/backtests/',
          serveJsonDir(path.join(logsDir, 'offline')))
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
