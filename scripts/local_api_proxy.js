#!/usr/bin/env node

/**
 * Simple local proxy to forward API requests to the remote dashboard backend.
 * This allows the Next.js dev server running on http://localhost:3000 to call
 * https://dashboard.hilovivo.com/api without tripping on CORS or TLS issues.
 */

const http = require('http');
const https = require('https');
const { URL } = require('url');

const TARGET_ORIGIN = 'https://dashboard.hilovivo.com';
const TARGET_HOSTNAME = 'dashboard.hilovivo.com';
const TARGET_PORT = 443;

const corsHeaders = {
  'Access-Control-Allow-Origin': 'http://localhost:3000',
  'Access-Control-Allow-Credentials': 'true',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, x-api-key',
  'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
  'Access-Control-Expose-Headers': '*',
};

const server = http.createServer((clientReq, clientRes) => {
  if (clientReq.method === 'OPTIONS') {
    clientRes.writeHead(204, corsHeaders);
    clientRes.end();
    return;
  }

  const targetUrl = new URL(clientReq.url, TARGET_ORIGIN);

  const requestOptions = {
    hostname: TARGET_HOSTNAME,
    port: TARGET_PORT,
    path: targetUrl.pathname + targetUrl.search,
    method: clientReq.method,
    headers: {
      ...clientReq.headers,
      host: TARGET_HOSTNAME,
    },
  };

  // Remove hop-by-hop headers
  delete requestOptions.headers['accept-encoding'];
  delete requestOptions.headers['content-length']; // will be set automatically if needed
  delete requestOptions.headers['origin'];
  delete requestOptions.headers['referer'];

  const proxyReq = https.request(requestOptions, (proxyRes) => {
    const headers = {
      ...proxyRes.headers,
      ...corsHeaders,
    };
    clientRes.writeHead(proxyRes.statusCode || 500, headers);
    proxyRes.pipe(clientRes, { end: true });
  });

  proxyReq.on('error', (error) => {
    console.error('[proxy] Upstream request failed:', error.message);
    if (!clientRes.headersSent) {
      clientRes.writeHead(502, {
        'Content-Type': 'application/json',
        ...corsHeaders,
      });
    }
    clientRes.end(JSON.stringify({ ok: false, error: 'Proxy request failed', detail: error.message }));
  });

  clientReq.pipe(proxyReq, { end: true });
});

const PORT = 8002;
server.listen(PORT, () => {
  console.log(`🔁 Local API proxy listening on http://localhost:${PORT}, forwarding to ${TARGET_ORIGIN}`);
});

