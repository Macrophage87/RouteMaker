/**
 * "Same ride or a new one?" (2026-11-05): asked once when the organiser copies or shares a Group or Mass Ride plan's
 * link, or starts its ride, and the plan's link went out more than 12 hours ago (lib/rideGroup.ts asksSameRide). Same
 * ride keeps the link's key; New ride makes a new ride id and key, then goes on. The platform's modal <dialog>: New
 * ride takes the focus, and Escape goes back with nothing sent or started.
 */
import { useEffect, useId, useRef } from "react";
import { NEW_RIDE, SAME_RIDE, SAME_RIDE_LEAD, SAME_RIDE_QUESTION } from "./lib/rideGroup.ts";

export function SameRideDialog({ open, onSame, onNew, onCancel }: { open: boolean; onSame: () => void; onNew: () => void; onCancel: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const newRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const leadId = useId();
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal?.();
      newRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
    }
  }, [open]);
  return (
    <dialog
      ref={dialogRef}
      className="ask-dialog same-ride-dialog"
      aria-labelledby={headingId}
      aria-describedby={leadId}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
    >
      {open && (
        <>
          <h2 id={headingId}>{SAME_RIDE_QUESTION}</h2>
          <p id={leadId}>{SAME_RIDE_LEAD}</p>
          <div className="closure-choices">
            <button type="button" ref={newRef} className="primary" onClick={onNew}>
              {NEW_RIDE}
            </button>
            <button type="button" className="secondary" onClick={onSame}>
              {SAME_RIDE}
            </button>
          </div>
        </>
      )}
    </dialog>
  );
}
