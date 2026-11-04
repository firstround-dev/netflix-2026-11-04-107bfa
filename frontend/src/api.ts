// Typed client for the backend API. All server errors surface as ApiError with a readable message.

export type TranslationStatus = "draft" | "approved" | "rejected";
export type TextSource = "ai" | "human";
export type SetStatus = "draft" | "locked";

export interface Translation {
  id: string;
  question_id: string;
  locale: string;
  prompt: string;
  options: string[];
  status: TranslationStatus;
  source: TextSource;
  updated_by: string;
  updated_at: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  version: number;
}

export interface Question {
  id: string;
  set_id: string;
  position: number;
  prompt: string;
  options: string[];
  correct_index: number;
  created_by: string;
  updated_at: string;
  translations: Record<string, Translation>;
}

export interface LocaleReadiness {
  total: number;
  approved: number;
  draft: number;
  rejected: number;
  missing: number;
}

export interface Readiness {
  ready: boolean;
  blockers: string[];
  per_locale: Record<string, LocaleReadiness>;
}

interface SetBase {
  id: string;
  title: string;
  locales: string[];
  status: SetStatus;
  created_by: string;
  created_at: string;
  locked_by: string | null;
  locked_at: string | null;
}

export interface SetSummary extends SetBase {
  question_count: number;
  ready: boolean;
}

export interface SetDetail extends SetBase {
  questions: Question[];
  readiness: Readiness;
}

export interface DeskEvent {
  id: number;
  set_id: string;
  question_id: string | null;
  translation_id: string | null;
  locale: string | null;
  actor: string;
  action: string;
  source: string | null;
  detail: string | null;
  at: string;
}

export interface DraftRunResult {
  created: number;
  skipped: number;
  failed: { question_id: string; locale: string; reason: string }[];
}

export interface LocaleInfo {
  code: string;
  name: string;
}

export interface QuestionInput {
  prompt: string;
  options: string[];
  correct_index: number;
  author: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

interface ValidationIssue {
  loc?: unknown[];
  msg?: string;
}

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((issue: ValidationIssue) => {
        const location = Array.isArray(issue.loc) ? issue.loc.filter((p) => p !== "body").join(".") : "";
        return location ? `${location}: ${issue.msg ?? "invalid"}` : (issue.msg ?? "invalid");
      })
      .join("; ");
  }
  return "Request failed";
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const data = (await response.json()) as { detail?: unknown };
      message = describe(data.detail);
    } catch {
      // keep the status text
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export const api = {
  locales: () => request<LocaleInfo[]>("GET", "/api/locales"),
  listSets: () => request<SetSummary[]>("GET", "/api/sets"),
  createSet: (body: { title: string; locales: string[]; created_by: string }) =>
    request<SetDetail>("POST", "/api/sets", body),
  getSet: (setId: string) => request<SetDetail>("GET", `/api/sets/${setId}`),
  events: (setId: string) => request<DeskEvent[]>("GET", `/api/sets/${setId}/events`),
  lockSet: (setId: string, locked_by: string) => request<SetDetail>("POST", `/api/sets/${setId}/lock`, { locked_by }),
  generateDrafts: (setId: string, body: { requested_by: string; locales?: string[]; overwrite_drafts?: boolean }) =>
    request<DraftRunResult>("POST", `/api/sets/${setId}/drafts`, body),
  addQuestion: (setId: string, body: QuestionInput) => request<Question>("POST", `/api/sets/${setId}/questions`, body),
  updateQuestion: (questionId: string, body: QuestionInput) =>
    request<Question>("PUT", `/api/questions/${questionId}`, body),
  deleteQuestion: (questionId: string, actor: string) =>
    request<void>("DELETE", `/api/questions/${questionId}?actor=${encodeURIComponent(actor)}`),
  editTranslation: (
    translationId: string,
    body: { prompt: string; options: string[]; edited_by: string; expected_version: number },
  ) => request<Translation>("PUT", `/api/translations/${translationId}`, body),
  approve: (translationId: string, body: { reviewer: string; expected_version: number }) =>
    request<Translation>("POST", `/api/translations/${translationId}/approve`, body),
  reject: (translationId: string, body: { reviewer: string; note: string; expected_version: number }) =>
    request<Translation>("POST", `/api/translations/${translationId}/reject`, body),
};
