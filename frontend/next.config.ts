import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // La URL del backend se resuelve en el cliente. En desarrollo apunta al
  // uvicorn local; en el deploy se define NEXT_PUBLIC_API_URL en Vercel.
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  },
};

export default nextConfig;
