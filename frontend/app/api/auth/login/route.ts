import { backendFetch } from "@/lib/server/backend";
import { clientKey, jsonError, loadConfig, NO_STORE, sameOrigin } from "@/lib/server/guard";
import { startSession } from "@/lib/server/session";

// The password is checked (and failed attempts throttled) by the API, which keeps the
// throttle in its database so it holds across serverless instances of this server.
export async function POST(request: Request): Promise<Response> {
  const config = loadConfig();
  if (config instanceof Response) return config;
  if (!sameOrigin(request, config)) return jsonError(403, "Cross-origin request refused.");

  const raw = await request.text();
  if (raw.length > 4096) return jsonError(413, "Request body too large.");
  let password: unknown;
  try {
    password = JSON.parse(raw).password;
  } catch {
    return jsonError(400, "Expected a JSON body with a password.");
  }
  if (typeof password !== "string" || password.length === 0 || password.length > 256) {
    return jsonError(400, "Enter the demo password.");
  }

  let upstream: Response;
  try {
    upstream = await backendFetch(config, "/auth/login", {
      method: "POST",
      contentType: "application/json",
      body: JSON.stringify({ password, client: clientKey(request, config) }),
    });
  } catch {
    return jsonError(502, "Sign-in is unavailable right now. Try again shortly.");
  }

  if (upstream.status === 200) {
    const session = await startSession(config);
    return Response.json({ ok: true, expiresAt: session.exp }, { headers: NO_STORE });
  }
  if (upstream.status === 401) return jsonError(401, "Incorrect password.");
  if (upstream.status === 429) {
    const retryAfter = upstream.headers.get("retry-after") ?? "900";
    const minutes = Math.max(1, Math.ceil(Number(retryAfter) / 60));
    return jsonError(429, `Too many failed sign-in attempts. Try again in about ${minutes} minute${minutes === 1 ? "" : "s"}.`, {
      "retry-after": retryAfter,
    });
  }
  console.error(`AdvisorLens sign-in failed upstream with status ${upstream.status}.`);
  return jsonError(502, "Sign-in is unavailable right now. Try again shortly.");
}
