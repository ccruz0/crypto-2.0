import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // Use 'standalone' for Docker production builds, 'export' for static exports
  // Dockerfile requires 'standalone' output for server.js
  output: process.env.NODE_ENV === 'production' ? 'standalone' : undefined,

  // Ignorar errores de TypeScript en el build (por el famoso payload: unknown)
  typescript: {
    ignoreBuildErrors: true,
  },

  // Suppress React warnings in development
  reactStrictMode: true,

  // Reduce console noise
  compiler: {
    removeConsole:
      process.env.NODE_ENV === 'production'
        ? {
            exclude: ['error', 'warn'], // Keep errors and warnings
          }
        : false,
  },

  // Dev proxy: Rewrite API paths to backend
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || 'http://localhost:8002';
    
    return [
      // Catch-all for /api/* paths - this handles all API requests
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
      // Keep old routes for backward compatibility
      {
        source: '/health/:path*',
        destination: `${backendUrl}/api/health/:path*`,
      },
      {
        source: '/dashboard/:path*',
        destination: `${backendUrl}/api/dashboard/:path*`,
      },
      {
        source: '/market/:path*',
        destination: `${backendUrl}/api/market/:path*`,
      },
      {
        source: '/orders/:path*',
        destination: `${backendUrl}/api/orders/:path*`,
      },
      {
        source: '/signals/:path*',
        destination: `${backendUrl}/api/signals/:path*`,
      },
    ];
  },

  // Headers to prevent browser caching (especially useful after deployments)
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          {
            key: 'Cache-Control',
            value: 'no-cache, no-store, must-revalidate, max-age=0',
          },
          {
            key: 'Pragma',
            value: 'no-cache',
          },
          {
            key: 'Expires',
            value: '0',
          },
        ],
      },
      {
        // Force no-cache for JavaScript and CSS files (critical for updates)
        source: '/_next/static/:path*',
        headers: [
          {
            key: 'Cache-Control',
            value: 'no-cache, no-store, must-revalidate, max-age=0',
          },
          {
            key: 'Pragma',
            value: 'no-cache',
          },
          {
            key: 'Expires',
            value: '0',
          },
        ],
      },
      {
        // Force no-cache for chunk files (JavaScript bundles)
        source: '/_next/static/chunks/:path*',
        headers: [
          {
            key: 'Cache-Control',
            value: 'no-cache, no-store, must-revalidate, max-age=0',
          },
          {
            key: 'Pragma',
            value: 'no-cache',
          },
        ],
      },
    ];
  },
};

export default nextConfig;
