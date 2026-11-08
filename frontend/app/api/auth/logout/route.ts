import { backendFetch } from "@/lib/server/backend";
import { jsonError, loadConfig, NO_STORE, sameOrigin } from "@/lib/server/guard";
import { getSession, isActive, sameToken } from "@/lib/server/session";

// Sign-out revokes the session ID on the API (so a copied cookie stops working
// everywhere) and clears the cookie in this browser.
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
      sessionId: session.sid,
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
  session.destroy();
  if (!revoked) {
    return jsonError(502, "Signed out in this browser, but the server could not record the sign-out.");
  }
  return new Response(null, { status: 204, headers: NO_STORE });
}
