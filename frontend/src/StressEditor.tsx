/**
 * The road panel's stress editor (OWNER-DECISIONS 441g, 441h, 441i, 460; lib/stressEditor.ts): an
 * instance admin's "Change LTS", in the same dialog as the panel, replacing its action row.
 *
 * - A native range control for the level, 1 to 5 in whole steps (half steps are a later phase).
 *   Its value is read as its words ("3, For experienced cyclists"), shown beside it in an
 *   `<output>`, and moves with the arrow keys, Home and End: no pointer needed. The panel itself is
 *   reached from the keyboard (I on the map, or Map tools in accessibility mode).
 * - "Only raise it", a category, a required private reason (never shown to riders) and an optional
 *   public note, each a labelled native control.
 * - The result is a sentence in a polite status region (always rendered, empty until it speaks); an
 *   error is an alert that names the field and moves the focus to it. Undo sits beside the message.
 * - The editor's heading takes the focus when it opens and after a save; Cancel and Escape close
 *   the editor (not the panel) and the caller returns the focus to the "Change LTS" button.
 */
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import {
  CATEGORY_LABEL,
  DISPLAY_LABEL,
  DISPLAY_OPTIONS,
  EDITOR_HEADING,
  LEVEL_LABEL,
  NOTE_HELP,
  NOTE_LABEL,
  RAISE_ONLY_HELP,
  RAISE_ONLY_LABEL,
  RAISE_ONLY_UNAVAILABLE,
  REASON_LABEL,
  countText,
  csrfFromCookie,
  currentText,
  fetchEditorState,
  formProblem,
  saveEdit,
  savedSaid,
  stepValueText,
  undoEdit,
  undoneSaid,
  type DisplayWhere,
  type EditResult,
  type EditorLoad,
  type EditorState,
} from "./lib/stressEditor.ts";

interface Props {
  origin: string;
  wayId: number;
  /** The road's name, for "This road piece". */
  title: string;
  /** Close the editor (Cancel, Escape, Done); the caller returns the focus to the Change LTS button. */
  onClose: () => void;
  /** A change or an undo was made: refresh the panel and the map's tiles. */
  onChanged: (generation: number) => void;
}

type Field = "reason" | "public_note" | "category" | "step" | "at_least" | "display";

export function StressEditor({ origin, wayId, title, onClose, onChanged }: Props) {
  const base = useId();
  const id = (part: string) => `${base}-${part}`;
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [load, setLoad] = useState<EditorLoad>({ kind: "loading" });
  const [step, setStep] = useState(3);
  const [atLeast, setAtLeast] = useState(false);
  const [category, setCategory] = useState("other");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [display, setDisplay] = useState<DisplayWhere>("route_only");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<{ field: Field | null; message: string } | null>(null);
  // What the status region says, and the change Undo would take back.
  const [said, setSaid] = useState("");
  const [saved, setSaved] = useState<EditResult | null>(null);

  const state: EditorState | null = load.kind === "ready" ? load.state : null;

  useEffect(() => {
    headingRef.current?.focus();
    const controller = new AbortController();
    fetchEditorState(origin, wayId, controller.signal).then(
      (next) => {
        setLoad(next);
        if (next.kind === "ready") {
          const { current, categories } = next.state;
          setStep(current.step);
          setCategory(categories.find((c) => c.id === (current.category ?? "other"))?.id ?? categories[0]?.id ?? "other");
        }
      },
      () => undefined,
    );
    return () => controller.abort();
  }, [origin, wayId]);

  const stepWords = state ? stepValueText(step, state.steps) : String(step);
  const raiseUnavailable = state ? !state.can_raise_only : false;
  const recent = state?.recent_edit?.can_undo && state.recent_edit.action === "set" ? state.recent_edit : null;
  const canUndo = saved !== null || recent !== null;
  const undoFor = saved?.edit_id ?? recent?.id ?? null;

  const focusField = (field: Field | null) => {
    if (!field) return;
    const target = document.getElementById(id(field));
    if (target) target.focus();
  };

  const fail = (field: Field | null, message: string) => {
    setError({ field, message });
    // The alert is rendered with the next paint; the field takes the focus after it.
    setTimeout(() => focusField(field), 0);
  };

  const refresh = () => {
    // A fresh editor state after a change: the token the next edit needs, and the "now" line.
    fetchEditorState(origin, wayId).then(
      (next) => {
        if (next.kind === "ready") setLoad(next);
      },
      () => undefined,
    );
  };

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!state || saving) return;
    const problem = formProblem({ reason, note }, state.reason_max, state.note_max);
    if (problem) {
      fail(problem.field, problem.message);
      return;
    }
    setError(null);
    setSaving(true);
    const outcome = await saveEdit(
      origin,
      {
        osm_way_ids: [wayId],
        step,
        at_least: atLeast,
        category,
        reason: reason.trim(),
        ...(note.trim() ? { public_note: note.trim(), display } : { display: "route_only" as const }),
        expected: state.expected,
      },
      csrfFromCookie(document.cookie),
    );
    setSaving(false);
    if (outcome.kind === "refused") {
      const field = (["reason", "public_note", "category", "step", "at_least", "display"] as const).find((f) => f === outcome.field);
      fail(field ?? null, outcome.message);
      // A stale edit: the road changed under the editor; show the new state for the next try.
      if (outcome.status === 409) refresh();
      return;
    }
    setSaved(outcome.result);
    setSaid(savedSaid(outcome.result, state.steps, atLeast));
    onChanged(outcome.result.generation);
    refresh();
    headingRef.current?.focus();
  };

  const onUndo = async () => {
    if (undoFor === null || !state || saving) return;
    setSaving(true);
    setError(null);
    const outcome = await undoEdit(origin, undoFor, csrfFromCookie(document.cookie));
    setSaving(false);
    if (outcome.kind === "refused") {
      fail(null, outcome.message);
      return;
    }
    setSaid(undoneSaid(outcome.result, state.steps));
    setSaved(null);
    onChanged(outcome.result.generation);
    refresh();
    headingRef.current?.focus();
  };


  return (
    <section className="stress-editor" aria-labelledby={id("title")}>
      <h3 id={id("title")} ref={headingRef} tabIndex={-1}>
        {EDITOR_HEADING}
      </h3>
      {load.kind === "loading" && <p className="stress-editor-status">Loading the road's level…</p>}
      {load.kind === "error" && (
        <>
          <p role="alert">{load.message}</p>
          <button type="button" className="secondary" onClick={onClose}>
            Close
          </button>
        </>
      )}
      {/* Always in the editor, empty at first: a region created holding its text is often not spoken. */}
      <p className="stress-editor-said" role="status">
        {said}
      </p>
      {error && (
        <p className="stress-editor-error" role="alert" id={id("error")}>
          {error.message}
        </p>
      )}
      {state && (
        <form onSubmit={onSubmit} noValidate aria-describedby={error ? id("error") : undefined}>
          <p className="stress-editor-now">{currentText(state.current, state.steps)}</p>
          <p className="stress-editor-extent">
            <span className="road-info-label">This road piece:</span> {title}
          </p>
          <div className="stress-editor-field">
            <label htmlFor={id("step")}>{LEVEL_LABEL}</label>
            <div className="stress-editor-slider">
              <input
                id={id("step")}
                type="range"
                min={1}
                max={5}
                step={1}
                value={step}
                aria-valuetext={stepWords}
                aria-describedby={id("ticks")}
                aria-invalid={error?.field === "step" ? true : undefined}
                onChange={(event) => setStep(Number(event.target.value))}
              />
              <output htmlFor={id("step")} className="stress-editor-output">
                {stepWords}
              </output>
            </div>
            <p id={id("ticks")} className="hint stress-editor-ticks">
              1 is the calmest, 5 is Avoid. Use the arrow keys to change the level; Home goes to 1 and End to 5.
            </p>
          </div>
          <div className="stress-editor-field stress-editor-check">
            <input
              id={id("at_least")}
              type="checkbox"
              checked={atLeast}
              disabled={raiseUnavailable}
              aria-describedby={id("raise-help")}
              onChange={(event) => setAtLeast(event.target.checked)}
            />
            <label htmlFor={id("at_least")}>{RAISE_ONLY_LABEL}</label>
            <p id={id("raise-help")} className="hint">
              {raiseUnavailable ? RAISE_ONLY_UNAVAILABLE : RAISE_ONLY_HELP}
            </p>
          </div>
          <div className="stress-editor-field">
            <label htmlFor={id("category")}>{CATEGORY_LABEL}</label>
            <select id={id("category")} value={category} onChange={(event) => setCategory(event.target.value)}>
              {state.categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label[0].toUpperCase() + c.label.slice(1)}
                </option>
              ))}
            </select>
          </div>
          <div className="stress-editor-field">
            <label htmlFor={id("reason")}>{REASON_LABEL}</label>
            <textarea
              id={id("reason")}
              rows={3}
              value={reason}
              required
              aria-required="true"
              aria-invalid={error?.field === "reason" ? true : undefined}
              aria-describedby={`${id("reason-count")}${error?.field === "reason" ? ` ${id("error")}` : ""}`}
              onChange={(event) => setReason(event.target.value)}
            />
            <p id={id("reason-count")} className="hint">
              Required. {countText(reason, state.reason_max)}.
            </p>
          </div>
          <div className="stress-editor-field">
            <label htmlFor={id("public_note")}>{NOTE_LABEL}</label>
            <input
              id={id("public_note")}
              type="text"
              value={note}
              aria-invalid={error?.field === "public_note" ? true : undefined}
              aria-describedby={`${id("note-help")}${error?.field === "public_note" ? ` ${id("error")}` : ""}`}
              onChange={(event) => setNote(event.target.value)}
            />
            <p id={id("note-help")} className="hint">
              {NOTE_HELP} {countText(note.trim(), state.note_max)}.
            </p>
          </div>
          {note.trim() !== "" && (
            <div className="stress-editor-field">
              <label htmlFor={id("display")}>{DISPLAY_LABEL}</label>
              <select
                id={id("display")}
                value={display}
                onChange={(event) => setDisplay(event.target.value as DisplayWhere)}
              >
                {DISPLAY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.text}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="stress-editor-buttons">
            <button type="submit" aria-disabled={saving ? true : undefined}>
              {saving ? "Saving…" : "Save"}
            </button>
            {canUndo && undoFor !== null && (
              <button type="button" className="secondary" onClick={onUndo} aria-disabled={saving ? true : undefined}>
                Undo the last change
              </button>
            )}
            <button type="button" className="secondary" onClick={onClose}>
              {saved ? "Done" : "Cancel"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
