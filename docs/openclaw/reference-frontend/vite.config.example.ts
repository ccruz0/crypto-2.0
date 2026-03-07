import { defineConfig } from "vite";

export default defineConfig({
  base: process.env.VITE_OPENCLAW_BASE_PATH || "/",
  // ... rest of your config
});
