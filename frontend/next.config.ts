import type { NextConfig } from "next";

// Split-host deployments (frontend on Vercel, backend on Render — or any
// two different domains) break the session cookie under modern browsers'
// third-party-cookie blocking: a cookie set by a cross-site fetch() call
// gets a perfectly valid Set-Cookie response (SameSite=None; Secure) but
// the browser silently refuses to store or resend it anyway, since it's
// a third-party cookie from the page's point of view. Proxying API calls
// through this same origin (the browser only ever talks to
// NEXT_PUBLIC's own host; Vercel forwards server-side to BACKEND_URL)
// makes the cookie first-party instead, which sidesteps the whole
// problem rather than fighting browser cookie policy. BACKEND_URL is
// deliberately not NEXT_PUBLIC_-prefixed — it's read by this rewrite
// config at request time on Vercel's server, never shipped to the
// browser, so the backend's real URL doesn't need to be public either.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/:path*` }];
  },
};

export default nextConfig;
