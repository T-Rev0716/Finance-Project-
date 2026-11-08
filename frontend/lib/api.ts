// All API traffic goes to this site's own authenticated server routes, which forward
// to the analysis service with a server-only credential. No API URL or secret is
// configured in the browser.
export const API_BASE = "/api";

let csrfToken: Promise<string> | null = null;

function redirectToSignIn(): void {
  if (typeof window === "undefined" || window.location.pathname === "/login") return;
  // Full navigation so the server re-checks access and in-memory data is discarded.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
}

function getCsrfToken(): Promise<string> {
  csrfToken ??= fetch(`${API_BASE}/auth/session`, { cache: "no-store" })
    .then(async (response) => {
      if (!response.ok) {
        if (response.status === 401) {
          redirectToSignIn();
          throw new Error("Your session has ended. Sign in again.");
        }
        throw new Error("The server could not confirm your session. Try again in a moment.");
      }
      return (await response.json()).csrfToken as string;
    })
    .catch((error: unknown) => {
      csrfToken = null; // Never cache a failure (e.g. offline): the next request asks again.
      throw error;
    });
  return csrfToken;
}

/** Fetch an API route with the session cookie, adding the CSRF token to state-changing requests. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const send = async () => {
    const headers = new Headers(init.headers);
    if (method !== "GET") headers.set("X-CSRF-Token", await getCsrfToken());
    return fetch(`${API_BASE}${path}`, { ...init, headers, cache: "no-store", credentials: "same-origin" });
  };
  let response = await send();
  if (response.status === 403 && method !== "GET") {
    csrfToken = null; // The session may have been replaced by a sign-in in another tab.
    response = await send();
  }
  if (response.status === 401) redirectToSignIn();
  return response;
}

export interface AllocationItem {
  name: string;
  market_value: number;
  weight_pct: number;
}

export interface TopHolding {
  ticker: string;
  security_name: string;
  asset_class: string;
  market_value: number;
  weight_pct: number;
  unrealized_gain_loss: number;
}

export interface PortfolioSummary {
  total_market_value: number;
  total_cost_basis: number;
  total_unrealized_gain_loss: number;
  total_unrealized_gain_loss_pct: number | null;
  holdings_count: number;
  asset_allocation: AllocationItem[];
  sector_allocation: AllocationItem[];
  account_type_allocation: AllocationItem[];
  top_holdings: TopHolding[];
}

export interface Flag {
  rule_id: string;
  severity: "high" | "medium" | "info";
  title: string;
  message: string;
  threshold: string;
  evidence: Record<string, unknown>;
}

export interface AnalysisResult {
  analysis_id: number;
  engine_version: string;
  source_name: string;
  file_sha256: string;
  client_profile: { risk_tolerance: string; client_goal: string };
  summary: PortfolioSummary;
  flags: Flag[];
  warnings: string[];
  disclaimer: string;
}

export interface SavedAnalysis {
  id: number;
  created_at: string;
  source_name: string;
  file_sha256: string;
  engine_version: string;
  risk_tolerance: string;
  client_goal: string;
  total_market_value: number;
  flag_count: number;
  has_brief: boolean;
}

export interface BriefSections {
  executive_summary: string[];
  portfolio_snapshot: {
    total_market_value: number;
    total_cost_basis: number;
    total_unrealized_gain_loss: number;
    holdings_count: number;
    risk_tolerance: string;
    client_goal: string;
    asset_allocation: AllocationItem[];
    sector_allocation: AllocationItem[];
    top_holdings: TopHolding[];
  };
  key_review_items: { rule_id: string; severity: Flag["severity"]; title: string; message: string }[];
  advisor_talking_points: string[];
  client_discussion_questions: string[];
  follow_up_items: string[];
  evidence_table: {
    rule_id: string;
    severity: string;
    threshold: string;
    evidence: Record<string, unknown>;
  }[];
  data_assumptions: string[];
  compliance_disclaimer: string;
}

export interface GeneratorMetadata {
  requested_generator?: string;
  provider?: string | null;
  model?: string | null;
  prompt_version?: string | null;
  validation_status?: string;
  fallback_reason?: string | null;
}

export interface Brief {
  analysis_id: number;
  source_name: string;
  generator: string;
  generator_metadata?: GeneratorMetadata;
  engine_version: string;
  generated_at: string;
  sections: BriefSections;
}

export interface GeneratorInfo {
  default_brief_generator: string;
  llm_configured: boolean;
  llm_model: string | null;
}

export const FALLBACK_DISCLAIMER =
  "Prepared for advisor review using synthetic data and deterministic rules only. " +
  "Every finding traces to the uploaded file. This is an advisor-support tool and does " +
  "not provide investment, tax, or legal advice.";

export async function fetchSamples(): Promise<string[]> {
  const res = await apiFetch("/samples");
  if (!res.ok) throw new Error(`Failed to load samples (${res.status})`);
  const body = await res.json();
  return body.samples;
}

export async function analyzeSample(name: string): Promise<AnalysisResult> {
  const res = await apiFetch(`/analyze/sample/${encodeURIComponent(name)}`, {
    method: "POST",
  });
  return handleAnalysisResponse(res);
}

export async function analyzeUpload(file: File): Promise<AnalysisResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiFetch("/analyze/upload", { method: "POST", body: form });
  return handleAnalysisResponse(res);
}

export async function listAnalyses(): Promise<SavedAnalysis[]> {
  const res = await apiFetch("/analyses");
  if (!res.ok) throw new Error(`Failed to load saved analyses (${res.status})`);
  return (await res.json()).analyses;
}

export async function getAnalysis(id: number): Promise<AnalysisResult> {
  const res = await apiFetch(`/analyses/${id}`);
  if (!res.ok) throw new Error(`Failed to load analysis ${id} (${res.status})`);
  const stored = await res.json();
  // Adapt the stored record to the analyze-response shape used by the dashboard.
  return {
    analysis_id: stored.id,
    engine_version: stored.engine_version,
    source_name: stored.source_name,
    file_sha256: stored.file_sha256,
    client_profile: {
      risk_tolerance: stored.risk_tolerance,
      client_goal: stored.client_goal,
    },
    summary: stored.summary,
    flags: stored.flags,
    warnings: stored.warnings,
    disclaimer: FALLBACK_DISCLAIMER,
  };
}

export async function getBrief(analysisId: number): Promise<Brief> {
  const res = await apiFetch(`/analyses/${analysisId}/brief`);
  if (!res.ok) throw new Error(`Failed to generate brief (${res.status})`);
  return res.json();
}

export async function regenerateBrief(analysisId: number, generator?: string): Promise<Brief> {
  const query = generator ? `?generator=${encodeURIComponent(generator)}` : "";
  const res = await apiFetch(`/analyses/${analysisId}/brief${query}`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to generate brief (${res.status})`);
  return res.json();
}

export async function fetchGeneratorInfo(): Promise<GeneratorInfo> {
  const res = await apiFetch("/generator");
  if (!res.ok) throw new Error(`Failed to load generator info (${res.status})`);
  const body = await res.json();
  return {
    default_brief_generator: body.default_brief_generator ?? "deterministic-v1",
    llm_configured: Boolean(body.llm_configured),
    llm_model: body.llm_model ?? null,
  };
}

export function briefExportUrl(analysisId: number, format: "markdown" | "html" | "pdf"): string {
  return `${API_BASE}/analyses/${analysisId}/brief/${format}`;
}

async function handleAnalysisResponse(res: Response): Promise<AnalysisResult> {
  const body = await res.json();
  if (!res.ok) {
    const detail = body?.detail;
    const errors: string[] = Array.isArray(detail?.errors)
      ? detail.errors
      : [typeof detail === "string" ? detail : "Analysis failed."];
    throw new Error(errors.join(" "));
  }
  return body as AnalysisResult;
}

export function formatMoney(value: number): string {
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export type ReviewStatus = "open" | "discussed" | "follow_up" | "resolved";
export interface ReviewEvent {
  finding_id: string;
  status: ReviewStatus;
  note: string;
  version: number;
  created_at: string;
}
export interface FindingReview {
  finding_id: string;
  flag: Flag;
  status: ReviewStatus;
  note: string;
  version: number;
  updated_at: string | null;
  history: ReviewEvent[];
}
export async function getReviews(analysisId: number): Promise<FindingReview[]> {
  const response = await apiFetch(`/analyses/${analysisId}/reviews`);
  if (!response.ok) throw new Error("Unable to load saved review decisions. Try again.");
  return (await response.json()).items;
}
export class ReviewSaveError extends Error {
  constructor(message: string, public statusCode: number) { super(message); }
}
export async function saveReview(analysisId: number, findingId: string, update: {
  status: ReviewStatus; note: string; expected_version: number;
}): Promise<Omit<FindingReview, "flag" | "history">> {
  const response = await apiFetch(`/analyses/${analysisId}/reviews/${findingId}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(update),
  });
  if (!response.ok) {
    const body = await response.json();
    const detail = typeof body.detail === "string" ? body.detail : "Review could not be saved. Check the status and note (maximum 4,000 characters).";
    throw new ReviewSaveError(detail, response.status);
  }
  return response.json();
}
