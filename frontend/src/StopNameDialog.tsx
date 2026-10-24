/**
 * A stop's name (Stephen 2026-10-24: a new stop "should also ask for a name"): the platform's modal <dialog>, as
 * Start ride on a computer's is. Asked as a stop is added (a Ctrl+click, or the road panel's Add as stop after a long
 * press) and from a stop's point menu (Name this stop, Rename stop). The name is optional: Add stop with the box empty
 * adds the stop unnamed, and the map's name for the spot is shown, as before. Enter is the main button; Escape is
 * Cancel, which adds nothing; on close the focus goes back where it was.
 */
import { useEffect, useId, useRef, useState } from "react";
import { STOP_NAME_ADD, STOP_NAME_CANCEL, STOP_NAME_HEADING, STOP_NAME_LABEL, STOP_NAME_MAX, STOP_NAME_SAVE } from "./lib/pointKinds.ts";

export interface StopNameAsk {
  /** "add": the stop is added on the main button; "rename": an existing stop's name changes. */
  mode: "add" | "rename";
  /** The name it has now (rename), or a place name to start from; empty for none. */
  name: string;
}

export function StopNameDialog({ ask, onDone, onCancel }: { ask: StopNameAsk | null; onDone: (name: string) => void; onCancel: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const inputId = useId();
  const [name, setName] = useState("");
  const open = ask !== null;
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      setName(ask?.name ?? "");
      dialog.showModal?.();
      inputRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
    }
  }, [open, ask]);
  return (
    <dialog
      ref={dialogRef}
      className="ask-dialog stop-name-dialog"
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
            onDone(name);
          }}
        >
          <h2 id={headingId}>{STOP_NAME_HEADING}</h2>
          <label htmlFor={inputId}>{STOP_NAME_LABEL}</label>
          <input
            id={inputId}
            ref={inputRef}
            type="text"
            value={name}
            maxLength={STOP_NAME_MAX}
            autoComplete="off"
            enterKeyHint="done"
            onChange={(event) => setName(event.target.value)}
          />
          <div className="closure-choices">
            <button type="submit" className="primary">
              {ask.mode === "add" ? STOP_NAME_ADD : STOP_NAME_SAVE}
            </button>
            <button type="button" className="secondary" onClick={onCancel}>
              {STOP_NAME_CANCEL}
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
}
