import "server-only";

// Server-only security configuration. None of these values may use a NEXT_PUBLIC_
// prefix: they must never be inlined into browser bundles.

export type Environment = "production" | "development" | "test";

export interface ServerConfig {
  environment: Environment;
  sessionSecret: string;
  sessionTtlSeconds: number;
  backendUrl: URL;
  backendSecret: string;
  publicOrigin: string;
  trustProxyHeaders: boolean;
  secureCookies: boolean;
  cookieName: string;
}

export class ServerConfigError extends Error {}

const ENVIRONMENTS: Environment[] = ["production", "development", "test"];
const MIN_SECRET_LENGTH = 32;
const PLACEHOLDER_PREFIX = "replace_me";

function secretProblems(name: string, value: string): string[] {
  if (value.length < MIN_SECRET_LENGTH) return [`${name} must be at least ${MIN_SECRET_LENGTH} characters.`];
  if (value.toLowerCase().startsWith(PLACEHOLDER_PREFIX)) return [`${name} still contains the placeholder value.`];
  if (!/^[\x21-\x7e]+$/.test(value)) return [`${name} must be printable ASCII without spaces.`];
  return [];
}

function parseUrl(name: string, value: string, problems: string[]): URL | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" && url.protocol !== "http:") throw new Error();
    if (url.username || url.password || url.search || url.hash || url.pathname !== "/") {
      problems.push(`${name} must be a bare origin such as https://host.example (no path, query or credentials).`);
    }
    return url;
  } catch {
    problems.push(`${name} must be an http(s) URL.`);
    return null;
  }
}

/**
 * Throws ServerConfigError when configuration is missing or invalid. Every caller turns
 * that into a denied request; there is no unprotected fallback.
 */
export function serverConfig(): ServerConfig {
  const env = process.env;
  const problems: string[] = [];
  const environment = (env.ADVISORLENS_ENV ?? "production").trim().toLowerCase() as Environment;
  if (!ENVIRONMENTS.includes(environment)) problems.push("ADVISORLENS_ENV must be production, development or test.");
  const production = environment === "production";

  const sessionSecret = env.ADVISORLENS_SESSION_SECRET ?? "";
  const backendSecret = env.ADVISORLENS_BACKEND_SECRET ?? "";
  problems.push(...secretProblems("ADVISORLENS_SESSION_SECRET", sessionSecret));
  problems.push(...secretProblems("ADVISORLENS_BACKEND_SECRET", backendSecret));
  if (sessionSecret && sessionSecret === backendSecret) {
    problems.push("ADVISORLENS_SESSION_SECRET and ADVISORLENS_BACKEND_SECRET must be different values.");
  }

  const backendUrl = parseUrl("ADVISORLENS_BACKEND_URL", env.ADVISORLENS_BACKEND_URL ?? "", problems);
  const publicOriginUrl = parseUrl("ADVISORLENS_PUBLIC_ORIGIN", env.ADVISORLENS_PUBLIC_ORIGIN ?? "", problems);
  if (production && backendUrl && backendUrl.protocol !== "https:") problems.push("ADVISORLENS_BACKEND_URL must use https in production.");
  if (production && publicOriginUrl && publicOriginUrl.protocol !== "https:") problems.push("ADVISORLENS_PUBLIC_ORIGIN must use https in production.");

  const ttlHours = Number(env.ADVISORLENS_SESSION_TTL_HOURS ?? "8");
  if (!Number.isFinite(ttlHours) || ttlHours < 0.25 || ttlHours > 24) {
    problems.push("ADVISORLENS_SESSION_TTL_HOURS must be between 0.25 and 24.");
  }

  if (problems.length > 0 || !backendUrl || !publicOriginUrl) throw new ServerConfigError(problems.join(" "));
  return {
    environment,
    sessionSecret,
    sessionTtlSeconds: Math.round(ttlHours * 3600),
    backendUrl,
    backendSecret,
    publicOrigin: publicOriginUrl.origin,
    trustProxyHeaders: env.ADVISORLENS_TRUST_PROXY_HEADERS === "true",
    secureCookies: production,
    // __Host- cookies must be Secure, host-only and Path=/; browsers enforce that.
    cookieName: production ? "__Host-advisorlens-session" : "advisorlens-session",
  };
}
