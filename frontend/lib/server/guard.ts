import "server-only";

import { serverConfig, ServerConfigError, type ServerConfig } from "./config";
import { getSession, isActive, sameToken, type ActiveSession } from "./session";

export const NO_STORE = { "cache-control": "no-store, private", pragma: "no-cache" } as const;

export function jsonError(status: number, detail: string, headers: Record<string, string> = {}): Response {
  return Response.json({ detail }, { status, headers: { ...NO_STORE, ...headers } });
}

export function loadConfig(): ServerConfig | Response {
  try {
    return serverConfig();
  } catch (error) {
    if (error instanceof ServerConfigError) {
      console.error("AdvisorLens access protection is misconfigured; denying requests.", error.message);
      return jsonError(503, "Access protection is not configured on this server.");
    }
    throw error;
  }
}

/**
 * State-changing requests must come from this site's own pages. Browsers always send
 * Origin on POST/PUT; a missing or foreign Origin is refused (fail closed).
 */
export function sameOrigin(request: Request, config: ServerConfig): boolean {
  return request.headers.get("origin") === config.publicOrigin;
}

export function clientKey(request: Request, config: ServerConfig): string {
  if (!config.trustProxyHeaders) return "untrusted-proxy";
  const forwarded = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return forwarded || request.headers.get("x-real-ip") || "unknown";
}

export async function requireApiSession(
  request: Request,
  { mutation }: { mutation: boolean },
): Promise<{ config: ServerConfig; session: ActiveSession } | Response> {
  const config = loadConfig();
  if (config instanceof Response) return config;
  if (mutation && !sameOrigin(request, config)) return jsonError(403, "Cross-origin request refused.");
  const session = await getSession(config);
  if (!isActive(session)) return jsonError(401, "Sign in to continue.");
  if (mutation && !sameToken(session.csrf, request.headers.get("x-csrf-token"))) {
    return jsonError(403, "Missing or invalid CSRF token. Reload the page and try again.");
  }
  return { config, session };
}
