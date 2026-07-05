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
