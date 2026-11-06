/**
 * A ride started away from its start and off its line (lib/navigate.ts startsAway; Stephen, 2026-11-06: "If someone is
 * off route, they should be given the option of going to the start or to reroute from there"): asked once, at the
 * ride's first fix. Go to the start makes the start stop 1 (RideMode rideToStart); Join from here rides on as any ride
 * off its line does, re-planned from here to the route. The platform's modal <dialog>, as Already done? is: Go to the
 * start takes the focus and Escape is Go to the start. Left unanswered while the rider rides on (RESTART_AUTO_M),
 * RideMode closes it for them.
 */
import { useEffect, useId, useRef } from "react";
import { START_ASK_HEADING, START_ASK_JOIN, START_ASK_LEAD, START_ASK_START } from "./lib/navigate.ts";

export function StartFirstDialog({ open, onChoose }: { open: boolean; onChoose: (start: boolean) => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const startRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const leadId = useId();
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal?.();
      startRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
    }
  }, [open]);
  return (
    <dialog
      ref={dialogRef}
      className="ask-dialog start-first-dialog"
      aria-labelledby={headingId}
      aria-describedby={leadId}
      onCancel={(event) => {
        event.preventDefault();
        onChoose(true);
      }}
    >
      {open && (
        <>
          <h2 id={headingId}>{START_ASK_HEADING}</h2>
          <p id={leadId}>{START_ASK_LEAD}</p>
          <div className="closure-choices">
            <button type="button" ref={startRef} className="primary" onClick={() => onChoose(true)}>
              {START_ASK_START}
            </button>
            <button type="button" className="secondary" onClick={() => onChoose(false)}>
              {START_ASK_JOIN}
            </button>
          </div>
        </>
      )}
    </dialog>
  );
}
