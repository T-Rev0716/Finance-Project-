import { jsonError, loadConfig, NO_STORE } from "@/lib/server/guard";
import { getSession, isActive } from "@/lib/server/session";

// Gives this site's own scripts the CSRF token for the current session. The token is
// useless to other origins: they cannot read this response, and mutations also
// require a matching Origin header.
export async function GET(): Promise<Response> {
  const config = loadConfig();
  if (config instanceof Response) return config;
  const session = await getSession(config);
  if (!isActive(session)) return jsonError(401, "Sign in to continue.");
  return Response.json({ csrfToken: session.csrf, expiresAt: session.exp }, { headers: NO_STORE });
}
