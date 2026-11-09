import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, "");
  const port = Number(env.VITE_PORT || process.env.VITE_PORT) || 5173;

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": path.resolve(import.meta.dirname, "./src"),
      },
    },
    server: {
      // Override with VITE_PORT in .env if this port is taken on your machine.
      // VITE_CLERK_SIGN_IN_URL / _SIGN_UP_URL must agree with it, or Clerk
      // redirects to a dead port.
      port,
      // Fail loudly instead of silently auto-incrementing, so the port in use
      // and the Clerk redirect URLs can never drift apart unnoticed.
      strictPort: true,
      /*
       * No /api proxy. The Express BFF has been removed: the browser calls the
       * FastAPI backend directly (see src/lib/backend.ts) and attaches Clerk's
       * own session token. That makes the backend a cross-origin request, which
       * is why ALLOWED_ORIGINS in the backend's .env must list this dev server's
       * origin.
       */
    },
    build: {
      outDir: "dist",
      sourcemap: true,
    },
  };
});

