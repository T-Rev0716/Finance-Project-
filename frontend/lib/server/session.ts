import "server-only";

import { randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import { getIronSession, type IronSession, type SessionOptions } from "iron-session";
import { cookies } from "next/headers";

import type { ServerConfig } from "./config";

// Sealed (encrypted + authenticated) cookie. A tampered or expired cookie unseals to an
// empty session. `exp` is an absolute expiry checked on every request; sessions are not
// extended by activity. `sid` lets the backend revoke this session on sign-out.
export interface DemoSession {
  sid: string;
  csrf: string;
  iat: number;
  exp: number;
}

export type ActiveSession = IronSession<DemoSession> & DemoSession;

function options(config: ServerConfig): SessionOptions {
  return {
    cookieName: config.cookieName,
    password: config.sessionSecret,
    ttl: config.sessionTtlSeconds,
    cookieOptions: { httpOnly: true, secure: config.secureCookies, sameSite: "lax", path: "/" },
  };
}

export async function getSession(config: ServerConfig): Promise<IronSession<DemoSession>> {
  return getIronSession<DemoSession>(await cookies(), options(config));
}

export function isActive(session: IronSession<DemoSession>): session is ActiveSession {
  return (
    typeof session.sid === "string" &&
    typeof session.csrf === "string" &&
    typeof session.exp === "number" &&
    session.exp > Date.now()
  );
}

export async function startSession(config: ServerConfig): Promise<ActiveSession> {
  const session = await getSession(config);
  const now = Date.now();
  // A fresh ID and CSRF token on every sign-in (no session fixation).
  session.sid = randomUUID();
  session.csrf = randomBytes(32).toString("base64url");
  session.iat = now;
  session.exp = now + config.sessionTtlSeconds * 1000;
  await session.save();
  return session as ActiveSession;
}

export function sameToken(expected: string, provided: string | null): boolean {
  if (!provided) return false;
  const a = Buffer.from(expected);
  const b = Buffer.from(provided);
  return a.length === b.length && timingSafeEqual(a, b);
}
