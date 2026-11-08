export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  const res = await fetch(`${API_BASE}/samples`);
  if (!res.ok) throw new Error(`Failed to load samples (${res.status})`);
  const body = await res.json();
  return body.samples;
}

export async function analyzeSample(name: string): Promise<AnalysisResult> {
  const res = await fetch(`${API_BASE}/analyze/sample/${encodeURIComponent(name)}`, {
    method: "POST",
  });
  return handleAnalysisResponse(res);
}

export async function analyzeUpload(file: File): Promise<AnalysisResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/analyze/upload`, { method: "POST", body: form });
  return handleAnalysisResponse(res);
}

export async function listAnalyses(): Promise<SavedAnalysis[]> {
  const res = await fetch(`${API_BASE}/analyses`);
  if (!res.ok) throw new Error(`Failed to load saved analyses (${res.status})`);
  return (await res.json()).analyses;
}

export async function getAnalysis(id: number): Promise<AnalysisResult> {
  const res = await fetch(`${API_BASE}/analyses/${id}`);
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
  const res = await fetch(`${API_BASE}/analyses/${analysisId}/brief`);
  if (!res.ok) throw new Error(`Failed to generate brief (${res.status})`);
  return res.json();
}

export async function regenerateBrief(analysisId: number, generator?: string): Promise<Brief> {
  const query = generator ? `?generator=${encodeURIComponent(generator)}` : "";
  const res = await fetch(`${API_BASE}/analyses/${analysisId}/brief${query}`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to generate brief (${res.status})`);
  return res.json();
}

export async function fetchGeneratorInfo(): Promise<GeneratorInfo> {
  const res = await fetch(`${API_BASE}/health`);
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
  const response = await fetch(`${API_BASE}/analyses/${analysisId}/reviews`, { cache: "no-store" });
  if (!response.ok) throw new Error("Unable to load saved review decisions. Try again.");
  return (await response.json()).items;
}
export class ReviewSaveError extends Error {
  constructor(message: string, public statusCode: number) { super(message); }
}
export async function saveReview(analysisId: number, findingId: string, update: {
  status: ReviewStatus; note: string; expected_version: number;
}): Promise<Omit<FindingReview, "flag" | "history">> {
  const response = await fetch(`${API_BASE}/analyses/${analysisId}/reviews/${findingId}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(update),
  });
  if (!response.ok) {
    const body = await response.json();
    const detail = typeof body.detail === "string" ? body.detail : "Review could not be saved. Check the status and note (maximum 4,000 characters).";
    throw new ReviewSaveError(detail, response.status);
  }
  return response.json();
}
