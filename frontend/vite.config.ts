/** Vite configuration for the React image website. */
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backend = 'http://localhost:8080'
const backendRoutes = [
  '/auth',
  '/feed',
  '/images',
  '/interactions',
  '/media',
  '/metadata',
  '/search',
  '/social',
  '/topics',
  '/users',
  '/behaviors',
]
const proxy = backendRoutes.reduce<Record<string, string>>((routes, route) => {
  routes[route] = backend
  return routes
}, {})

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy,
  },
})
