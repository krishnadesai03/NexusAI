import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The bottom-left "N" badge is Next.js's own dev-mode route indicator — never present in a
  // production build regardless, but turned off explicitly so it doesn't show during local dev.
  devIndicators: false,
};

export default nextConfig;
