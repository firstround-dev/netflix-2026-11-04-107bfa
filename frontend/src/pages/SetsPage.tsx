import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useActor } from "../actor";
import { api, errorMessage, type LocaleInfo, type SetSummary } from "../api";
import { ErrorText, formatTime } from "../components";

export function SetsPage() {
  const { actor } = useActor();
  const navigate = useNavigate();
  const [sets, setSets] = useState<SetSummary[] | null>(null);
  const [locales, setLocales] = useState<LocaleInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.listSets().then(setSets).catch((caught) => setError(errorMessage(caught)));
    api.locales().then(setLocales).catch((caught) => setError(errorMessage(caught)));
  }, []);

  function toggleLocale(code: string) {
    setChosen((current) => (current.includes(code) ? current.filter((c) => c !== code) : [...current, code]));
  }

  async function createSet(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api.createSet({ title, locales: chosen, created_by: actor });
      navigate(`/sets/${created.id}`);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Question sets</h1>
      <ErrorText error={error} />
      {sets === null ? (
        <p className="muted">Loading…</p>
      ) : sets.length === 0 ? (
        <p className="muted">No question sets yet. Create the first one below.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Episode</th>
              <th>Locales</th>
              <th>Questions</th>
              <th>Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {sets.map((set) => (
              <tr key={set.id}>
                <td>
                  <Link to={`/sets/${set.id}`}>{set.title}</Link>
                </td>
                <td>{set.locales.join(", ")}</td>
                <td>{set.question_count}</td>
                <td>
                  {set.status === "locked" ? (
                    <span className="badge set-locked">Locked</span>
                  ) : set.ready ? (
                    <span className="badge status-approved">Ready to lock</span>
                  ) : (
                    <span className="badge status-draft">In progress</span>
                  )}
                </td>
                <td className="muted">
                  {set.created_by}, {formatTime(set.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <section className="card">
        <h2>New question set</h2>
        <form onSubmit={createSet} className="form">
          <label>
            Episode title
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Episode 12: Movie Night" required />
          </label>
          <fieldset>
            <legend>Target locales</legend>
            <div className="chips">
              {locales.map((locale) => (
                <label key={locale.code} className={`chip ${chosen.includes(locale.code) ? "chip-on" : ""}`}>
                  <input type="checkbox" checked={chosen.includes(locale.code)} onChange={() => toggleLocale(locale.code)} />
                  {locale.code} <span className="muted">{locale.name}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="actions">
            <button type="submit" disabled={busy || !actor || !title.trim() || chosen.length === 0}>
              Create set
            </button>
            {!actor && <span className="muted">Enter your name at the top to create a set.</span>}
          </div>
        </form>
      </section>
    </>
  );
}
