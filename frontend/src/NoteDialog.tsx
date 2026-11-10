/**
 * A route note (lib/routeNotes.ts; Stephen 2026-11-10, "put a mechanism in in plan"): the platform's modal <dialog>, as
 * a stop's name is asked (StopNameDialog.tsx). Opened from the map's long-press menu (Add note) for a new note, and
 * from a note's sign on the map to change or remove it. Its kind (Caution or Point of interest) and its words; Enter is
 * the main button; Escape is Cancel, which changes nothing; on close the focus goes back where it was.
 */
import { useEffect, useId, useRef, useState } from "react";
import {
  NOTE_CANCEL,
  NOTE_HEADING_ADD,
  NOTE_HEADING_EDIT,
  NOTE_HINT,
  NOTE_KIND_LABEL,
  NOTE_KIND_WORDS,
  NOTE_REMOVE,
  NOTE_SAVE,
  NOTE_TEXT_LABEL,
  NOTE_ADD,
  NOTE_ICON_LABEL,
  NOTE_ICON_WORDS,
} from "./lib/routeNotesPlan.ts";
import { KIND_ICON, NOTE_ICONS, NOTE_TEXT_MAX, cleanNoteText, type NoteIcon, type NoteKind } from "./lib/routeNotes.ts";
// What is said as a note changes, from here so the page's Plan-only words stay out of Go and Ride's modules.
export { noteSaid, noteTooLongSaid, notesFullSaid } from "./lib/routeNotesPlan.ts";

export interface NoteAsk {
  /** "add": a new note at the spot; "edit": the note at `index`. */
  mode: "add" | "edit";
  index?: number;
  kind: NoteKind;
  text: string;
  icon: NoteIcon;
}

export function NoteDialog({
  ask,
  onDone,
  onRemove,
  onCancel,
  fallbackFocus,
}: {
  ask: NoteAsk | null;
  /** Where the focus goes when what opened the dialog is gone (a note's sign, drawn again as the note changed). */
  fallbackFocus?: () => HTMLElement | null;
  onDone: (kind: NoteKind, text: string, icon: NoteIcon) => void;
  onRemove: () => void;
  onCancel: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const inputId = useId();
  const hintId = useId();
  const [kind, setKind] = useState<NoteKind>("caution");
  const [text, setText] = useState("");
  const [icon, setIcon] = useState<NoteIcon>("warning");
  const open = ask !== null;
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      setKind(ask?.kind ?? "caution");
      setText(ask?.text ?? "");
      setIcon(ask?.icon ?? KIND_ICON[ask?.kind ?? "caution"]);
      dialog.showModal?.();
      inputRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
      // A note's sign is drawn again once the note changes, after this runs: the map then.
      if (opener.current instanceof HTMLElement && opener.current.isConnected && !opener.current.classList.contains("route-note")) opener.current.focus();
      else fallbackFocus?.()?.focus();
    }
  }, [open, ask]);
  const empty = cleanNoteText(text) === "";
  return (
    <dialog
      ref={dialogRef}
      className="ask-dialog note-dialog"
      aria-labelledby={headingId}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
    >
      {ask && (
        <form
          method="dialog"
          onSubmit={(event) => {
            event.preventDefault();
            if (!empty) onDone(kind, cleanNoteText(text), icon);
          }}
        >
          <h2 id={headingId}>{ask.mode === "add" ? NOTE_HEADING_ADD : NOTE_HEADING_EDIT}</h2>
          <fieldset className="note-kind">
            <legend>{NOTE_KIND_LABEL}</legend>
            {(["caution", "interest"] as const).map((k) => (
              <label key={k}>
                <input
                  type="radio"
                  name="note-kind"
                  value={k}
                  checked={kind === k}
                  onChange={() => {
                    // The kind's own icon follows the kind; one the rider chose stays.
                    if (icon === KIND_ICON[kind]) setIcon(KIND_ICON[k]);
                    setKind(k);
                  }}
                />
                {NOTE_KIND_WORDS[k]}
              </label>
            ))}
          </fieldset>
          <fieldset className="note-icons">
            <legend>{NOTE_ICON_LABEL}</legend>
            {(Object.keys(NOTE_ICONS) as NoteIcon[]).map((k) => (
              <label key={k} className="note-icon-choice" title={NOTE_ICON_WORDS[k]}>
                <input type="radio" name="note-icon" value={k} checked={icon === k} onChange={() => setIcon(k)} aria-label={NOTE_ICON_WORDS[k]} />
                <span aria-hidden="true">{NOTE_ICONS[k]}</span>
              </label>
            ))}
          </fieldset>
          <label htmlFor={inputId}>{NOTE_TEXT_LABEL}</label>
          <input
            id={inputId}
            ref={inputRef}
            type="text"
            value={text}
            maxLength={NOTE_TEXT_MAX}
            autoComplete="off"
            enterKeyHint="done"
            aria-describedby={hintId}
            onChange={(event) => setText(event.target.value)}
          />
          <p id={hintId} className="hint">
            {NOTE_HINT}
          </p>
          <div className="closure-choices">
            <button type="submit" className="primary" aria-disabled={empty ? true : undefined}>
              {ask.mode === "add" ? NOTE_ADD : NOTE_SAVE}
            </button>
            {ask.mode === "edit" && (
              <button type="button" className="secondary" onClick={onRemove}>
                {NOTE_REMOVE}
              </button>
            )}
            <button type="button" className="secondary" onClick={onCancel}>
              {NOTE_CANCEL}
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
}
