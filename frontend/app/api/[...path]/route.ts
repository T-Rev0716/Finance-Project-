import { backendFetch } from "@/lib/server/backend";
import { jsonError, NO_STORE, requireApiSession } from "@/lib/server/guard";

// Authenticated, constrained proxy to the analysis API. Only the routes and methods
// below are forwarded, to the fixed backend from configuration, with headers built
// here. Anything else returns 404/405 without contacting the backend.

type Method = "GET" | "POST" | "PUT";
interface Route {
  method: Method;
  pattern: RegExp;
  query?: string[];
  maxBody?: number;
}

const ID = "\\d{1,9}";
const JSON_LIMIT = 64 * 1024;
const UPLOAD_LIMIT = 1_000_000 + 64 * 1024; // Backend's 1 MB file limit plus multipart overhead.

const ROUTES: Route[] = [
  { method: "GET", pattern: /^generator$/ },
  { method: "GET", pattern: /^samples$/ },
  { method: "POST", pattern: /^analyze\/sample\/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}\.csv$/ },
  { method: "POST", pattern: /^analyze\/upload$/, maxBody: UPLOAD_LIMIT },
  { method: "GET", pattern: /^analyses$/, query: ["limit"] },
  { method: "GET", pattern: new RegExp(`^analyses/${ID}$`) },
  { method: "GET", pattern: new RegExp(`^analyses/${ID}/brief$`) },
  { method: "POST", pattern: new RegExp(`^analyses/${ID}/brief$`), query: ["generator"] },
  { method: "GET", pattern: new RegExp(`^analyses/${ID}/brief/(markdown|html|pdf)$`) },
  { method: "GET", pattern: new RegExp(`^analyses/${ID}/reviews$`) },
  { method: "PUT", pattern: new RegExp(`^analyses/${ID}/reviews/[0-9a-f]{24}$`) },
  { method: "GET", pattern: /^households$/ },
  { method: "POST", pattern: /^households$/ },
  { method: "GET", pattern: new RegExp(`^households/${ID}$`) },
  { method: "PUT", pattern: new RegExp(`^households/${ID}$`) },
  { method: "GET", pattern: new RegExp(`^households/${ID}/versions$`) },
  { method: "GET", pattern: new RegExp(`^analyses/${ID}/household$`) },
  { method: "POST", pattern: new RegExp(`^analyses/${ID}/household$`) },
  { method: "GET", pattern: new RegExp(`^analyses/${ID}/reports/draft$`) },
  { method: "POST", pattern: new RegExp(`^analyses/${ID}/reports/preview$`) },
  { method: "GET", pattern: new RegExp(`^analyses/${ID}/reports$`) },
  { method: "POST", pattern: new RegExp(`^analyses/${ID}/reports$`) },
  { method: "GET", pattern: new RegExp(`^reports/${ID}$`) },
  { method: "GET", pattern: new RegExp(`^reports/${ID}/(markdown|html|pdf)$`) },
];

// Only these backend response headers reach the browser.
const RESPONSE_HEADERS = ["content-type", "content-disposition", "x-content-sha256", "retry-after"];

type Context = { params: Promise<{ path: string[] }> };

async function readLimited(request: Request, limit: number): Promise<ArrayBuffer | null> {
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > limit) return null;
  if (!request.body) return new ArrayBuffer(0);
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > limit) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body.buffer;
}

function forwardedContentType(request: Request, route: Route): string | undefined {
  const type = request.headers.get("content-type") ?? "";
  if (route.maxBody === UPLOAD_LIMIT) return type.startsWith("multipart/form-data;") ? type : undefined;
  return type.startsWith("application/json") ? "application/json" : undefined;
}

async function proxy(request: Request, context: Context, method: Method): Promise<Response> {
  const { path } = await context.params;
  if (path.some((s) => s === "" || s === "." || s === ".." || /[\\/]/.test(s))) return jsonError(404, "Not found.");
  const joined = path.join("/");
  const route = ROUTES.find((r) => r.method === method && r.pattern.test(joined));
  if (!route) {
    const otherMethod = ROUTES.some((r) => r.pattern.test(joined));
    return otherMethod ? jsonError(405, "Method not allowed.") : jsonError(404, "Not found.");
  }

  const access = await requireApiSession(request, { mutation: method !== "GET" });
  if (access instanceof Response) return access;
  const { config, session } = access;

  const incoming = new URL(request.url).searchParams;
  const query = new URLSearchParams();
  for (const key of route.query ?? []) {
    const value = incoming.get(key);
    if (value !== null) query.set(key, value);
  }

  let body: ArrayBuffer | undefined;
  let contentType: string | undefined;
  if (method !== "GET") {
    const limited = await readLimited(request, route.maxBody ?? JSON_LIMIT);
    if (limited === null) return jsonError(413, "Request body too large.");
    contentType = forwardedContentType(request, route);
    if (limited.byteLength > 0 && !contentType) return jsonError(415, "Unsupported content type.");
    body = limited.byteLength > 0 ? limited : undefined;
  }

  const backendPath = `/${path.map(encodeURIComponent).join("/")}${query.size ? `?${query}` : ""}`;
  let upstream: Response;
  try {
    upstream = await backendFetch(config, backendPath, { method, session, contentType, body });
  } catch {
    return jsonError(502, "The analysis service is unavailable. Try again shortly.");
  }

  if (upstream.status === 401) {
    if (upstream.headers.get("x-advisorlens-auth") === "session") {
      session.destroy();
      return jsonError(401, "Your session has ended. Sign in again.");
    }
    console.error("AdvisorLens backend rejected the server credentials; check ADVISORLENS_BACKEND_SECRET.");
    return jsonError(502, "The analysis service rejected this server's credentials.");
  }

  const headers = new Headers({ ...NO_STORE, "x-content-type-options": "nosniff" });
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  if ((headers.get("content-type") ?? "").startsWith("text/html")) {
    // Exported reports are documents, not app pages: no scripts, no access to this origin.
    headers.set("content-security-policy", "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:");
  }
  return new Response(await upstream.arrayBuffer(), { status: upstream.status, headers });
}

export function GET(request: Request, context: Context) {
  return proxy(request, context, "GET");
}

export function POST(request: Request, context: Context) {
  return proxy(request, context, "POST");
}

export function PUT(request: Request, context: Context) {
  return proxy(request, context, "PUT");
}
