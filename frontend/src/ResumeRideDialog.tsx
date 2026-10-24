/**
 * A ride left going when the page closed (lib/rideResume.ts): the platform's modal <dialog>, as Start ride on a computer's
 * is. Resume ride is first and takes the focus; Not now forgets it; Escape (or Android's back) only puts it away, so it is asked
 * again at the next load; on close the focus goes back.
 */
import { useEffect, useId, useRef } from "react";
import { RESUME_HEADING, RESUME_LEAD, RESUME_NOT_NOW, RESUME_RIDE } from "./lib/rideResume.ts";

export function ResumeRideDialog({ open, onResume, onNotNow, onLater }: { open: boolean; onResume: () => void; onNotNow: () => void; onLater: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const resumeRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const leadId = useId();
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal?.();
      resumeRef.current?.focus();
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
        onLater();
      }}
    >
      {open && (
        <>
          <h2 id={headingId}>{RESUME_HEADING}</h2>
          <p id={leadId}>{RESUME_LEAD}</p>
          <div className="closure-choices">
            <button type="button" ref={resumeRef} className="primary" onClick={onResume}>
              {RESUME_RIDE}
            </button>
            <button type="button" className="secondary" onClick={onNotNow}>
              {RESUME_NOT_NOW}
            </button>
          </div>
        </>
      )}
    </dialog>
  );
}
