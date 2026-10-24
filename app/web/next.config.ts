import type { NextConfig } from "next";

// Static export so `npm run build` emits a fully static bundle into
// src/security_lakehouse/web/dist/ — Python wheel ships it, no Node in prod.
// basePath '/console' matches the Python server route.
//
// Next.js requires output inside the web workspace. The build script copies
// the completed static export into the Python package after Next succeeds.
// Keep development chunks in .next so their runtime imports resolve locally.
const isDev = process.env.NODE_ENV === "development";

// `npm run build:demo` sets both: the read-only live demo replays a recorded
// API snapshot and is hosted under a different path. Defined explicitly so
// the normal build inlines "" and drops every demo code path at compile time.
const demoSnapshot = process.env.NEXT_PUBLIC_DEMO_SNAPSHOT === "1";
const basePath = process.env.CONSOLE_BASE_PATH || "/console";
if (!/^(\/[A-Za-z0-9._-]+)+$/.test(basePath))
  throw new Error(`CONSOLE_BASE_PATH must look like /console, got ${basePath}`);

const config: NextConfig = {
  output: "export",
  basePath,
  assetPrefix: basePath,
  trailingSlash: true,
  distDir: isDev ? ".next" : "out",
  cleanDistDir: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  typescript: { ignoreBuildErrors: false },
  env: {
    NEXT_PUBLIC_DEMO_SNAPSHOT: demoSnapshot ? "1" : "",
    NEXT_PUBLIC_CONSOLE_BASE_PATH: basePath,
  },
};

export default config;
