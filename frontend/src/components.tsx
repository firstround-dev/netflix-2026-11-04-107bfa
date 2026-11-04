import { useCallback, useEffect, useState } from "react";
import { api, errorMessage, type LocaleReadiness, type SetDetail, type TextSource, type TranslationStatus } from "./api";

export const OPTION_LETTERS = ["A", "B", "C", "D"];

export function formatTime(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString();
}

export function StatusBadge({ status }: { status: TranslationStatus | "missing" }) {
  const label = { draft: "Draft", approved: "Approved", rejected: "Rejected", missing: "No draft" }[status];
  return <span className={`badge status-${status}`}>{label}</span>;
}

export function SourceBadge({ source }: { source: TextSource }) {
  return <span className={`badge source-${source}`}>{source === "ai" ? "AI draft" : "Human text"}</span>;
}

export function LockedBanner({ set }: { set: SetDetail }) {
  if (set.status !== "locked") return null;
  return (
    <div className="banner banner-locked">
      Locked for broadcast by <strong>{set.locked_by}</strong> on {formatTime(set.locked_at)}. Nothing in this set can
      change.
    </div>
  );
}

export function ErrorText({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p className="error" role="alert">
      {error}
    </p>
  );
}

export function ReadinessSummary({ readiness }: { readiness: LocaleReadiness }) {
  const done = readiness.total > 0 && readiness.approved === readiness.total;
  return (
    <span className={`readiness ${done ? "readiness-done" : ""}`}>
      {readiness.approved}/{readiness.total} approved
      {readiness.draft > 0 && <span className="muted"> · {readiness.draft} draft</span>}
      {readiness.rejected > 0 && <span className="muted"> · {readiness.rejected} rejected</span>}
      {readiness.missing > 0 && <span className="muted"> · {readiness.missing} missing</span>}
    </span>
  );
}

/** Load a question set and re-fetch it after every change so the UI always reflects the server. */
export function useSet(setId: string) {
  const [set, setSet] = useState<SetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    try {
      setSet(await api.getSet(setId));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }, [setId]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { set, error, reload };
}
