import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "src"),
    },
  },
  test: {
    environment: "jsdom",
    include: [
      "src/**/*.{test,spec}.{ts,tsx}",
      "server/**/*.{test,spec}.js",
    ],
    env: {
      // server/clerk.js fails fast at import time when Clerk is unconfigured,
      // which is the desired behaviour for a real deploy. Tests need harmless
      // placeholders so importing the BFF succeeds.
      CLERK_PUBLISHABLE_KEY: "pk_test_vitest",
      CLERK_SECRET_KEY: "sk_test_vitest",
      BACKEND_API_URL: "http://localhost:8000",
    },
  },
});
