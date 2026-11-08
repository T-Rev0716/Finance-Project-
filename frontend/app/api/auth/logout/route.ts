import { backendFetch } from "@/lib/server/backend";
import { jsonError, loadConfig, NO_STORE, sameOrigin } from "@/lib/server/guard";
import { getSession, isActive, sameToken } from "@/lib/server/session";

// Sign-out revokes the session ID on the API (so a copied cookie stops working
// everywhere) and only then clears the cookie in this browser. If revocation fails the
// cookie is kept, so the browser can retry and is not told it has signed out.
export async function POST(request: Request): Promise<Response> {
  const config = loadConfig();
  if (config instanceof Response) return config;
  if (!sameOrigin(request, config)) return jsonError(403, "Cross-origin request refused.");
  const session = await getSession(config);
  if (!isActive(session)) {
    session.destroy();
    return new Response(null, { status: 204, headers: NO_STORE });
  }
  if (!sameToken(session.csrf, request.headers.get("x-csrf-token"))) {
    return jsonError(403, "Missing or invalid CSRF token. Reload the page and try again.");
  }

  let revoked = false;
  try {
    const upstream = await backendFetch(config, "/auth/logout", {
      method: "POST",
      session,
      contentType: "application/json",
      body: JSON.stringify({ expires_at: session.exp / 1000 }),
    });
    // 401 "session" means it was already revoked; a credentials 401 is a misconfiguration.
    revoked =
      upstream.status === 204 ||
      (upstream.status === 401 && upstream.headers.get("x-advisorlens-auth") === "session");
  } catch {
    revoked = false;
  }
  if (!revoked) {
    return jsonError(502, "The server could not record the sign-out, so you are still signed in. Try again shortly.");
  }
  session.destroy();
  return new Response(null, { status: 204, headers: NO_STORE });
}
