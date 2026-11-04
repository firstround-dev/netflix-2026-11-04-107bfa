import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useActor } from "../actor";
import { api, errorMessage, type DeskEvent, type DraftRunResult, type Question, type QuestionInput, type SetDetail } from "../api";
import { ErrorText, LockedBanner, OPTION_LETTERS, ReadinessSummary, StatusBadge, formatTime, useSet } from "../components";

export function SetPage() {
  const { setId = "" } = useParams();
  const { set, error, reload } = useSet(setId);

  if (error && !set) return <ErrorText error={error} />;
  if (!set) return <p className="muted">Loading…</p>;

  const locked = set.status === "locked";
  return (
    <>
      <p>
        <Link to="/">← All sets</Link>
      </p>
      <div className="page-head">
        <h1>{set.title}</h1>
        {locked ? <span className="badge set-locked">Locked</span> : <span className="badge status-draft">In progress</span>}
      </div>
      <p className="muted">
        Created by {set.created_by} on {formatTime(set.created_at)}
      </p>
      <LockedBanner set={set} />
      <ErrorText error={error} />

      <LocalePanel set={set} />
      <ProducerActions set={set} onChange={reload} />

      <h2>Questions</h2>
      {set.questions.length === 0 && <p className="muted">No questions yet.</p>}
      {set.questions.map((question, index) => (
        <QuestionCard key={question.id} index={index + 1} question={question} set={set} onChange={reload} />
      ))}
      {!locked && <AddQuestion set={set} onChange={reload} />}

      <ActivityLog setId={set.id} version={set} />
    </>
  );
}

function LocalePanel({ set }: { set: SetDetail }) {
  return (
    <section className="locale-grid">
      {set.locales.map((locale) => (
        <div key={locale} className="card locale-card">
          <div className="locale-head">
            <strong>{locale}</strong>
            <Link to={`/sets/${set.id}/review/${locale}`}>Review →</Link>
          </div>
          <ReadinessSummary readiness={set.readiness.per_locale[locale]} />
        </div>
      ))}
    </section>
  );
}

function ProducerActions({ set, onChange }: { set: SetDetail; onChange: () => Promise<void> }) {
  const { actor } = useActor();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draftResult, setDraftResult] = useState<DraftRunResult | null>(null);
  const [showBlockers, setShowBlockers] = useState(false);

  if (set.status === "locked") return null;
  const canAct = Boolean(actor) && !busy;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await onChange();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  const missing = Object.values(set.readiness.per_locale).reduce((sum, locale) => sum + locale.missing, 0);

  return (
    <section className="card">
      <div className="actions">
        <button
          disabled={!canAct || set.questions.length === 0}
          onClick={() => run(async () => setDraftResult(await api.generateDrafts(set.id, { requested_by: actor })))}
        >
          Draft missing translations with AI{missing > 0 ? ` (${missing})` : ""}
        </button>
        <button
          className="primary"
          disabled={!canAct || !set.readiness.ready}
          onClick={() => {
            if (window.confirm("Lock this set for broadcast? It cannot be changed afterwards.")) {
              void run(async () => {
                await api.lockSet(set.id, actor);
              });
            }
          }}
        >
          Lock for broadcast
        </button>
        {!set.readiness.ready && (
          <button className="link" onClick={() => setShowBlockers((v) => !v)}>
            {set.readiness.blockers.length} thing{set.readiness.blockers.length === 1 ? "" : "s"} before this can lock
          </button>
        )}
        {!actor && <span className="muted">Enter your name at the top to make changes.</span>}
      </div>
      {showBlockers && (
        <ul className="blockers">
          {set.readiness.blockers.map((blocker) => (
            <li key={blocker}>{blocker}</li>
          ))}
        </ul>
      )}
      {draftResult && (
        <p className="note">
          Drafted {draftResult.created}, skipped {draftResult.skipped} already present
          {draftResult.failed.length > 0 && (
            <>
              , <strong>{draftResult.failed.length} failed</strong> (left missing, try again):
              <ul>
                {draftResult.failed.map((failure) => (
                  <li key={`${failure.question_id}-${failure.locale}`}>
                    {failure.locale}: {failure.reason}
                  </li>
                ))}
              </ul>
            </>
          )}
          .
        </p>
      )}
      <ErrorText error={error} />
    </section>
  );
}

function QuestionCard({
  index,
  question,
  set,
  onChange,
}: {
  index: number;
  question: Question;
  set: SetDetail;
  onChange: () => Promise<void>;
}) {
  const { actor } = useActor();
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const locked = set.status === "locked";

  async function remove() {
    if (!window.confirm(`Delete question ${index} and all its translations?`)) return;
    try {
      await api.deleteQuestion(question.id, actor);
      await onChange();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  if (editing) {
    return (
      <section className="card">
        <h3>Q{index}</h3>
        <p className="note">Changing the prompt or options sends every translation of this question back to draft.</p>
        <QuestionForm
          initial={question}
          submitLabel="Save question"
          onCancel={() => setEditing(false)}
          onSubmit={async (values) => {
            await api.updateQuestion(question.id, { ...values, author: actor });
            setEditing(false);
            await onChange();
          }}
        />
      </section>
    );
  }

  return (
    <section className="card question-card">
      <div className="question-head">
        <h3>Q{index}</h3>
        {!locked && (
          <span className="actions">
            <button className="link" disabled={!actor} onClick={() => setEditing(true)}>
              Edit
            </button>
            <button className="link danger" disabled={!actor} onClick={remove}>
              Delete
            </button>
          </span>
        )}
      </div>
      <p className="prompt">{question.prompt}</p>
      <ol className="options">
        {question.options.map((option, i) => (
          <li key={i} className={i === question.correct_index ? "correct" : ""}>
            <span className="letter">{OPTION_LETTERS[i]}</span> {option}
            {i === question.correct_index && <span className="muted"> ✓ correct</span>}
          </li>
        ))}
      </ol>
      <div className="chips">
        {set.locales.map((locale) => {
          const translation = question.translations[locale];
          return (
            <Link key={locale} to={`/sets/${set.id}/review/${locale}`} className="chip">
              {locale} <StatusBadge status={translation ? translation.status : "missing"} />
            </Link>
          );
        })}
      </div>
      <ErrorText error={error} />
    </section>
  );
}

function AddQuestion({ set, onChange }: { set: SetDetail; onChange: () => Promise<void> }) {
  const { actor } = useActor();
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <button disabled={!actor} onClick={() => setOpen(true)}>
        + Add question
      </button>
    );
  }
  return (
    <section className="card">
      <h3>New question</h3>
      <QuestionForm
        submitLabel="Add question"
        onCancel={() => setOpen(false)}
        onSubmit={async (values) => {
          await api.addQuestion(set.id, { ...values, author: actor });
          setOpen(false);
          await onChange();
        }}
      />
    </section>
  );
}

type QuestionValues = Omit<QuestionInput, "author">;

function QuestionForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial?: QuestionValues;
  submitLabel: string;
  onSubmit: (values: QuestionValues) => Promise<void>;
  onCancel: () => void;
}) {
  const [prompt, setPrompt] = useState(initial?.prompt ?? "");
  const [options, setOptions] = useState<string[]>(initial?.options ?? ["", "", "", ""]);
  const [correctIndex, setCorrectIndex] = useState(initial?.correct_index ?? 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit({ prompt, options, correct_index: correctIndex });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <label>
        Prompt
        <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={2} maxLength={500} required />
      </label>
      <div className="option-rows">
        {options.map((option, i) => (
          <label key={i} className="option-row">
            <input
              type="radio"
              name="correct"
              checked={correctIndex === i}
              onChange={() => setCorrectIndex(i)}
              title="Correct answer"
            />
            <span className="letter">{OPTION_LETTERS[i]}</span>
            <input
              value={option}
              maxLength={200}
              required
              onChange={(e) => setOptions(options.map((o, j) => (j === i ? e.target.value : o)))}
            />
          </label>
        ))}
      </div>
      <p className="muted">Select the radio button next to the correct answer.</p>
      <div className="actions">
        <button type="submit" className="primary" disabled={busy}>
          {submitLabel}
        </button>
        <button type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
      <ErrorText error={error} />
    </form>
  );
}

function ActivityLog({ setId, version }: { setId: string; version: SetDetail }) {
  const [events, setEvents] = useState<DeskEvent[]>([]);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    api.events(setId).then(setEvents).catch(() => setEvents([]));
  }, [setId, open, version]);

  return (
    <details className="card" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>Activity log</summary>
      {events.length === 0 ? (
        <p className="muted">Nothing recorded yet.</p>
      ) : (
        <table className="table compact">
          <thead>
            <tr>
              <th>When</th>
              <th>Who</th>
              <th>What</th>
              <th>Locale</th>
              <th>Text from</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.id}>
                <td className="muted">{formatTime(event.at)}</td>
                <td>{event.actor}</td>
                <td>{event.action.replaceAll("_", " ")}</td>
                <td>{event.locale ?? ""}</td>
                <td>{event.source ?? ""}</td>
                <td className="muted">{event.detail ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
  );
}
