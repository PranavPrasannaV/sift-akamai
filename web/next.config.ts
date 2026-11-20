import type { NextConfig } from "next";

/*
  Two settings, both deliberate.

  turbopack.root pins the workspace to this directory. Without it the bundler
  walks up past the repository looking for a lockfile and warns about one it
  found in a home directory.

  No image loader, no font loader, no analytics, no telemetry-bearing plugin:
  the demo runs with the network physically off, and this application talks to
  exactly one origin, the local FastAPI process.
*/

/*
  On Akamai the dashboard is the one public origin (port 80). Everything the
  Python process serves is proxied to it on the same machine: the JSON API the
  pages read, the AI pages, /health, and their stylesheet. "standalone" builds a
  self-contained server for the Linode.
*/
const API = process.env.SIFT_API_INTERNAL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  turbopack: {
    root: import.meta.dirname,
  },
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${API}/api/v1/:path*` },
      { source: "/ai/:path*", destination: `${API}/ai/:path*` },
      { source: "/health", destination: `${API}/health` },
      { source: "/files/:path*", destination: `${API}/files/:path*` },
      { source: "/static/:path*", destination: `${API}/static/:path*` },
    ];
  },
};

export default nextConfig;
