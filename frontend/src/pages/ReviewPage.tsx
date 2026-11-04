import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { useActor } from "../actor";
import { api, errorMessage, type Question, type Translation } from "../api";
import {
  ErrorText,
  LockedBanner,
  OPTION_LETTERS,
  ReadinessSummary,
  SourceBadge,
  StatusBadge,
  formatTime,
  useSet,
} from "../components";

export function ReviewPage() {
  const { setId = "", locale = "" } = useParams();
  const { set, error, reload } = useSet(setId);
  const { actor } = useActor();
  const [draftError, setDraftError] = useState<string | null>(null);

  if (error && !set) return <ErrorText error={error} />;
  if (!set) return <p className="muted">Loading…</p>;
  if (!set.locales.includes(locale)) return <p className="error">This set does not target {locale}.</p>;

  const locked = set.status === "locked";
  const readiness = set.readiness.per_locale[locale];

  async function draftMissing() {
    setDraftError(null);
    try {
      const result = await api.generateDrafts(setId, { requested_by: actor, locales: [locale] });
      if (result.failed.length > 0) {
        setDraftError(result.failed.map((f) => `${f.reason}`).join("; "));
      }
      await reload();
    } catch (caught) {
      setDraftError(errorMessage(caught));
    }
  }

  return (
    <>
      <p>
        <Link to={`/sets/${set.id}`}>← {set.title}</Link>
      </p>
      <div className="page-head">
        <h1>Review {locale}</h1>
        <ReadinessSummary readiness={readiness} />
      </div>
      <LockedBanner set={set} />
      <ErrorText error={error} />
      {!locked && readiness.missing > 0 && (
        <div className="actions">
          <button disabled={!actor} onClick={draftMissing}>
            Draft {readiness.missing} missing translation{readiness.missing === 1 ? "" : "s"} with AI
          </button>
          {!actor && <span className="muted">Enter your name at the top to make changes.</span>}
        </div>
      )}
      <ErrorText error={draftError} />
      {!locked && actor && (
        <p className="note">
          Edit the {locale} text on the right, then approve. Keep the options in the same order as the English: the
          correct answer is matched by position.
        </p>
      )}
      {set.questions.map((question, index) => (
        <ReviewCard
          key={question.id}
          index={index + 1}
          question={question}
          locale={locale}
          translation={question.translations[locale]}
          locked={locked}
          onChange={reload}
        />
      ))}
    </>
  );
}

function ReviewCard({
  index,
  question,
  locale,
  translation,
  locked,
  onChange,
}: {
  index: number;
  question: Question;
  locale: string;
  translation: Translation | undefined;
  locked: boolean;
  onChange: () => Promise<void>;
}) {
  const { actor } = useActor();
  const [prompt, setPrompt] = useState(translation?.prompt ?? "");
  const [options, setOptions] = useState<string[]>(translation?.options ?? ["", "", "", ""]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");

  // Whenever the server copy changes (a save, someone else's review, a redraft), reset the editor to it.
  const serverVersion = translation ? `${translation.id}:${translation.version}` : "";
  useEffect(() => {
    setPrompt(translation?.prompt ?? "");
    setOptions(translation?.options ?? ["", "", "", ""]);
    setRejecting(false);
    setNote("");
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverVersion]);

  const dirty =
    translation !== undefined &&
    (prompt !== translation.prompt || options.some((option, i) => option !== translation.options[i]));
  const canAct = Boolean(actor) && !locked && !busy && translation !== undefined;

  async function run(action: (current: Translation) => Promise<void>) {
    if (!translation) return;
    setBusy(true);
    setError(null);
    try {
      await action(translation);
      await onChange();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  const save = (current: Translation) =>
    api.editTranslation(current.id, { prompt, options, edited_by: actor, expected_version: current.version });

  return (
    <section className={`card review-card status-border-${translation?.status ?? "missing"}`}>
      <div className="question-head">
        <h3>Q{index}</h3>
        <span className="badges">
          <StatusBadge status={translation?.status ?? "missing"} />
          {translation && <SourceBadge source={translation.source} />}
        </span>
      </div>

      <div className="review-grid">
        <div className="col-head">English</div>
        <div className="col-head">{locale}</div>

        <Row label="Prompt" english={question.prompt}>
          {translation ? (
            <textarea value={prompt} rows={2} maxLength={500} disabled={!canAct} onChange={(e) => setPrompt(e.target.value)} />
          ) : (
            <span className="muted">No draft yet</span>
          )}
        </Row>
        {question.options.map((english, i) => (
          <Row key={i} label={`Option ${OPTION_LETTERS[i]}`} english={english} correct={i === question.correct_index}>
            {translation ? (
              <input
                value={options[i]}
                maxLength={200}
                disabled={!canAct}
                onChange={(e) => setOptions(options.map((o, j) => (j === i ? e.target.value : o)))}
              />
            ) : (
              <span className="muted">—</span>
            )}
          </Row>
        ))}
      </div>

      {translation && (
        <p className="muted small">
          Text last changed by {translation.updated_by} on {formatTime(translation.updated_at)}
          {translation.status === "approved" && translation.reviewed_by && (
            <>
              {" "}· approved by <strong>{translation.reviewed_by}</strong> on {formatTime(translation.reviewed_at)}
            </>
          )}
          {translation.status === "rejected" && translation.reviewed_by && (
            <>
              {" "}· rejected by <strong>{translation.reviewed_by}</strong>: “{translation.review_note}”
            </>
          )}
          {translation.status === "draft" && translation.review_note && (
            <>
              {" "}· <strong>{translation.review_note}</strong>
            </>
          )}
        </p>
      )}

      {translation && !locked && (
        <div className="actions">
          {dirty ? (
            <>
              <button className="primary" disabled={!canAct} onClick={() => run(async (c) => void (await save(c)))}>
                Save edit
              </button>
              <button
                disabled={!canAct}
                onClick={() =>
                  run(async (current) => {
                    const saved = await save(current);
                    await api.approve(saved.id, { reviewer: actor, expected_version: saved.version });
                  })
                }
              >
                Save and approve
              </button>
              <button
                className="link"
                disabled={busy}
                onClick={() => {
                  setPrompt(translation.prompt);
                  setOptions(translation.options);
                }}
              >
                Discard changes
              </button>
            </>
          ) : (
            <>
              {translation.status !== "approved" && (
                <button
                  className="primary"
                  disabled={!canAct}
                  onClick={() =>
                    run(async (current) => {
                      await api.approve(current.id, { reviewer: actor, expected_version: current.version });
                    })
                  }
                >
                  Approve
                </button>
              )}
              {translation.status !== "rejected" && !rejecting && (
                <button className="danger" disabled={!canAct} onClick={() => setRejecting(true)}>
                  Reject…
                </button>
              )}
            </>
          )}
          {!actor && <span className="muted">Enter your name at the top to review.</span>}
        </div>
      )}

      {rejecting && translation && (
        <div className="reject-box">
          <label>
            Why is this rejected?
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} autoFocus />
          </label>
          <div className="actions">
            <button
              className="danger"
              disabled={!canAct || !note.trim()}
              onClick={() =>
                run(async (current) => {
                  await api.reject(current.id, { reviewer: actor, note, expected_version: current.version });
                })
              }
            >
              Confirm rejection
            </button>
            <button className="link" onClick={() => setRejecting(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      <ErrorText error={error} />
    </section>
  );
}

function Row({ label, english, correct, children }: { label: string; english: string; correct?: boolean; children: ReactNode }) {
  return (
    <>
      <div className={`cell english ${correct ? "correct" : ""}`}>
        <span className="cell-label">
          {label}
          {correct && <span className="muted"> ✓ correct</span>}
        </span>
        <span>{english}</span>
      </div>
      <div className="cell">
        <span className="cell-label">{label}</span>
        {children}
      </div>
    </>
  );
}
