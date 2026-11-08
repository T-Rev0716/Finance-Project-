import { API_BASE, apiFetch, Flag, ReviewStatus } from "./api";

export type ReportFormat = "markdown" | "html" | "pdf";

export interface DraftReview {
  finding_id: string;
  title: string;
  severity: Flag["severity"];
  status: ReviewStatus;
  version: number;
  internal_note: string;
}

export interface DraftDefaults {
  analysis_id: number;
  brief_id: number | null;
  client_summary: string;
  reviews: DraftReview[];
  household: {
    household_id: number;
    version: number;
    name: string;
    as_of: string;
    has_priorities: boolean;
    goal_count: number;
    account_count: number;
  } | null;
}

export interface ReportDraft {
  brief_id: number;
  client_summary: string;
  follow_ups: { finding_id: string; review_version: number; client_text: string }[];
  household: {
    household_id: number;
    version: number;
    priorities: boolean;
    goals: boolean;
    accounts: boolean;
  } | null;
}

export interface ReportPreview {
  preview_sha256: string;
  html: string;
}

export interface ApprovedReport {
  id: number;
  analysis_id: number;
  approved_at: string;
  content_sha256: string;
  files: Record<ReportFormat, string>;
}

export class ReportError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function request<T>(path: string, method = "GET", payload?: unknown): Promise<T> {
  const response = await apiFetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg).join("; ")
          : "The report request failed. Please try again.";
    throw new ReportError(message, response.status);
  }
  return data as T;
}

export const getDraftDefaults = (analysisId: number) =>
  request<DraftDefaults>(`/analyses/${analysisId}/reports/draft`);

export const previewReport = (analysisId: number, draft: ReportDraft) =>
  request<ReportPreview>(`/analyses/${analysisId}/reports/preview`, "POST", draft);

export const approveReport = (analysisId: number, draft: ReportDraft, previewSha256: string) =>
  request<ApprovedReport>(`/analyses/${analysisId}/reports`, "POST", {
    draft,
    preview_sha256: previewSha256,
  });

export const listReports = (analysisId: number) =>
  request<{ reports: ApprovedReport[] }>(`/analyses/${analysisId}/reports`).then((r) => r.reports);

export const reportFileUrl = (reportId: number, format: ReportFormat) =>
  `${API_BASE}/reports/${reportId}/${format}`;
