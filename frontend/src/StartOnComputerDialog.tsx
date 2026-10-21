/**
 * Start ride on a computer (lib/startOnComputer.ts): the platform's modal <dialog>, as the closure warning is. Go back
 * is first and takes the focus; Escape is Go back; on close the focus goes back where it was.
 */
import { useEffect, useId, useRef } from "react";
import { COMPUTER_ANYWAY, COMPUTER_BACK, COMPUTER_HEADING, COMPUTER_LEAD } from "./lib/startOnComputer.ts";

export function StartOnComputerDialog({ open, onBack, onAnyway }: { open: boolean; onBack: () => void; onAnyway: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const backRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const leadId = useId();
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal?.();
      backRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
    }
  }, [open]);
  return (
    <dialog
      ref={dialogRef}
      className="start-computer-dialog"
      aria-labelledby={headingId}
      aria-describedby={leadId}
      onCancel={(event) => {
        event.preventDefault();
        onBack();
      }}
    >
      {open && (
        <>
          <h2 id={headingId}>{COMPUTER_HEADING}</h2>
          <p id={leadId}>{COMPUTER_LEAD}</p>
          <div className="closure-choices">
            <button type="button" ref={backRef} className="primary" onClick={onBack}>
              {COMPUTER_BACK}
            </button>
            <button type="button" className="secondary" onClick={onAnyway}>
              {COMPUTER_ANYWAY}
            </button>
          </div>
        </>
      )}
    </dialog>
  );
}
