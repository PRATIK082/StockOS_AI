import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  eslint: { ignoreDuringBuilds: true },
  // LAN hosts allowed to open the dev server (e.g. phone on the same Wi-Fi).
  // Override with ALLOWED_DEV_ORIGINS="host1,host2".
  allowedDevOrigins: process.env.ALLOWED_DEV_ORIGINS
    ? process.env.ALLOWED_DEV_ORIGINS.split(",")
        .map((s) => s.trim())
        .filter(Boolean)
    : ["192.168.1.6", "192.168.1.8"],
};

export default nextConfig;