import "server-only";

import { redirect } from "next/navigation";
import { connection } from "next/server";

import { backendFetch } from "./backend";
import { serverConfig, ServerConfigError } from "./config";
import { getSession, isActive } from "./session";

export type PageAccess = "granted" | "misconfigured" | "unavailable";
type SessionState = PageAccess | "signed-out";

export function loginPath(next: string): string {
  return `/login?next=${encodeURIComponent(next)}`;
}

/**
 * The cookie alone is not enough: the API must also confirm the session has not been
 * signed out. Pages and the sign-in page share this check, so they always agree (a
 * revoked-but-unexpired cookie must not bounce between them).
 */
export async function pageSessionState(): Promise<SessionState> {
  // Never prerender: the decision must be made per request, not at build time.
  await connection();
  let config;
  try {
    config = serverConfig();
  } catch (error) {
    if (error instanceof ServerConfigError) {
      console.error("AdvisorLens access protection is misconfigured; denying page access.", error.message);
      return "misconfigured";
    }
    throw error;
  }
  const session = await getSession(config);
  if (!isActive(session)) return "signed-out";
  try {
    const response = await backendFetch(config, "/auth/session", { method: "GET", sessionId: session.sid });
    if (response.status === 204) return "granted";
    if (response.status === 401 && response.headers.get("x-advisorlens-auth") === "session") return "signed-out";
    return "unavailable";
  } catch {
    return "unavailable";
  }
}

/** Guards a protected page: sign-in for any non-current session; deny (never open) on errors. */
export async function requirePageSession(next: string): Promise<PageAccess> {
  const state = await pageSessionState();
  if (state === "signed-out") redirect(loginPath(next));
  return state;
}
