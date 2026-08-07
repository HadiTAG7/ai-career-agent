import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Vercel packages Next.js itself. The standalone bundle is only needed by our Docker image.
  output: process.env.BUILD_STANDALONE === "true" ? "standalone" : undefined,
  agentRules: false,
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
};

export default nextConfig;
