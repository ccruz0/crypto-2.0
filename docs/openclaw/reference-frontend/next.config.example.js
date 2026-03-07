/** @type {import('next').NextConfig} */
const basePath = process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || "";
const nextConfig = {
  basePath: basePath || undefined,
  assetPrefix: basePath || undefined,
  // ... rest of your config
};
module.exports = nextConfig;
