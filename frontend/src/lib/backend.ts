/**
 * Bridge from the browser to the FastAPI backend.
 *
 * HISTORY — why this file exists. The frontend used to call a same-origin
 * `/api/*` BFF (an Express server) which held CLERK_SECRET_KEY, attached a
 * bearer token, and forwarded to FastAPI. That server has been removed: the
 * browser now talks to FastAPI directly and sends the Clerk session JWT itself.
 *
 * Nothing here is a secret. CLERK_SECRET_KEY stays server-side inside Clerk and
 * FastAPI; the browser only ever holds the short-lived session token that
 * Clerk's own SDK mints. FastAPI verifies it against Clerk's JWKS in
 * backend/app/auth.py.
 *
 * The one thing this file must get right is the path mapping. The old BFF had
 * its own tidy URL scheme; FastAPI's routes are different. Keeping the mapping
 * in one table means a backend route rename is a one-line change here rather
 * than eleven edits across four files.
 */

const DEFAULT_ORIGIN = "http://localhost:8000";

/** Base URL of the FastAPI backend. VITE_-prefixed so Vite exposes it. */
export const BACKEND_ORIGIN = (
  import.meta.env.VITE_BACKEND_API_URL || DEFAULT_ORIGIN
).replace(/\/+$/, "");

/*
 * Clerk session-token provider.
 *
 * `useAuth()` is a React hook, but api.ts and speech.ts are plain modules called
 * from event handlers deep in the tree. App.tsx registers Clerk's getToken here
 * once at mount; until it does, requests go out unauthenticated and FastAPI
 * answers 401 — which is the correct, visible failure for an unauthenticated
 * caller.
 */
type TokenProvider = () => Promise<string | null>;
let getClerkToken: TokenProvider | null = null;

/** Called once from App.tsx with Clerk's useAuth().getToken. */
export function registerTokenProvider(fn: TokenProvider | null) {
  getClerkToken = fn;
}

/** The bearer header for an outbound request, or fallback guest token when signed out. */
export async function authHeaders(): Promise<Record<string, string>> {
  if (getClerkToken) {
    try {
      const token = await getClerkToken();
      if (token) return { Authorization: `Bearer ${token}` };
    } catch {
      // Fall through to guest token on Clerk error
    }
  }
  const guestToken = localStorage.getItem("guest_auth_token") || "guest_demo_user";
  return { Authorization: `Bearer ${guestToken}` };
}


/*
 * BFF path -> FastAPI path.
 *
 * Keys are the paths the frontend historically requested; values are what
 * FastAPI actually serves.
 */
const PATH_MAP: Record<string, string> = {
  /*
   * /api/chat is the NON-streaming JSON route; /api/chat/stream is SSE.
   *
   * Upstream corrected this in the Next.js handlers (it had been streaming
   * both), so the mapping follows: sendChat() in api.ts does r.json() against a
   * typed ChatResponse and could never have worked against an SSE body.
   * The live UI uses sendChatStream(), so this is contract accuracy rather than
   * a behaviour change.
   */
  "/api/chat": "/chat",
  "/api/chat/stream": "/chat/stream",
  "/api/grievance/detect": "/grievances",
  "/api/grievance/answer": "/grievances/answer",
  "/api/grievance/clarify": "/grievances/clarify",
  "/api/grievance/finalize": "/grievances/finalize",
  "/api/speak": "/voice/speak",
  "/api/voice/speak": "/voice/speak",
  "/api/voice/transcribe": "/voice/transcribe",
  "/api/translate": "/translate",
};

/**
 * Rewrites a BFF-style path to the FastAPI path, preserving the query string.
 * GET /api/grievance/fields?conversation_id=X&language=hi becomes
 * GET /grievances/X/fields?language=hi, because FastAPI takes the conversation
 * id as a path parameter rather than a query parameter.
 * Unknown paths are passed through unchanged.
 */
export function backendPath(path: string): string {
  const [pathname, query = ""] = path.split("?");

  if (pathname === "/api/grievance/fields") {
    const params = new URLSearchParams(query);
    const conversationId = params.get("conversation_id") ?? "";
    params.delete("conversation_id");
    const rest = params.toString();
    return `/grievances/${encodeURIComponent(conversationId)}/fields${rest ? `?${rest}` : ""}`;
  }

  if (pathname.startsWith("/api/documents/pdf/")) {
    // Already correct: FastAPI serves /documents/pdf/{filename} too. The BFF
    // had been URL-encoding the filename; so do we, once.
    return pathname.replace("/api/documents/pdf/", "/documents/pdf/") + (query ? `?${query}` : "");
  }

  const mapped = PATH_MAP[pathname];
  return (mapped ?? pathname) + (query ? `?${query}` : "");
}

/** Absolute URL for a BFF-style path. */
export function backendUrl(path: string): string {
  return `${BACKEND_ORIGIN}${backendPath(path)}`;
}

/**
 * fetch() against the backend, with the Clerk bearer token attached.
 *
 * Replaces every bare `fetch("/api/...")` in the app. Callers keep passing the
 * old paths so the diff stays small and the mapping stays in one table.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers: Record<string, string> = {
    ...(await authHeaders()),
    ...((init.headers as Record<string, string>) ?? {}),
  };
  return fetch(backendUrl(path), { ...init, headers });
}
