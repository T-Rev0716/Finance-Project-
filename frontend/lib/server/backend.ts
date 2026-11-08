import "server-only";

import type { ServerConfig } from "./config";

const SECRET_HEADER = "x-advisorlens-backend-secret";
const SESSION_HEADER = "x-advisorlens-session";
const ISSUED_HEADER = "x-advisorlens-session-issued-at";

/**
 * The only way this server talks to the API: a fixed destination from configuration,
 * a path built by the caller from allowlisted segments, and headers set here rather
 * than copied from the browser request.
 */
export async function backendFetch(
  config: ServerConfig,
  path: string,
  init: {
    method: string;
    session?: { sid: string; issuedAt: number };
    contentType?: string;
    body?: ArrayBuffer | string;
  },
): Promise<Response> {
  if (!path.startsWith("/") || path.startsWith("//")) throw new Error("Backend paths must be absolute.");
  const url = new URL(path, config.backendUrl);
  if (url.origin !== config.backendUrl.origin) throw new Error("Backend destination is fixed.");
  const headers = new Headers({ [SECRET_HEADER]: config.backendSecret });
  if (init.session) {
    headers.set(SESSION_HEADER, init.session.sid);
    headers.set(ISSUED_HEADER, String(init.session.issuedAt));
  }
  if (init.contentType) headers.set("content-type", init.contentType);
  return fetch(url, {
    method: init.method,
    headers,
    body: init.body,
    cache: "no-store",
    redirect: "manual",
    signal: AbortSignal.timeout(60_000),
  });
}
