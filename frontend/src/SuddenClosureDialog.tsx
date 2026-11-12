/**
 * A closure that came up on the route ahead during a ride (lib/closureWatch.ts; Stephen 2026-11-12: "If the route takes
 * you onto one, pop up a notice and offer a reroute"): what is closed and how far ahead, said urgently as it opens, and
 * two choices, Reroute around it (the default, where the focus starts) and Keep going. The platform's modal <dialog>, as
 * Start first is; Escape is Keep going. `children` are the ride's live regions while it is open (the modal makes the
 * ride's own inert), so its cues are still heard.
 */
import { useEffect, useId, useRef, type ReactNode } from "react";
import { CLOSED_AHEAD, KEEP_GOING, REROUTE_AROUND_IT } from "./lib/closureWatch.ts";

export interface SuddenAsk {
  name: string;
  /** "2.1 mi (3.4 km)". */
  distance: string;
  /** Metres along the ride's line where the closure ends: ridden past, the dialog closes by itself. */
  toM: number;
  /** Where it was asked: ridden far enough from there unanswered, it closes by itself. */
  at: [number, number] | null;
}

export function SuddenClosureDialog({ ask, onReroute, onKeep, children }: { ask: SuddenAsk | null; onReroute: () => void; onKeep: () => void; children?: ReactNode }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const rerouteRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const leadId = useId();
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (ask && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal?.();
      rerouteRef.current?.focus();
    } else if (!ask && dialog.open) {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
    }
  }, [ask]);
  return (
    <dialog
      ref={dialogRef}
      className="ask-dialog sudden-closure-dialog"
      aria-labelledby={headingId}
      aria-describedby={leadId}
      onCancel={(event) => {
        event.preventDefault();
        onKeep();
      }}
    >
      {children}
      {ask && (
        <>
          <h2 id={headingId}>
            {CLOSED_AHEAD} · {ask.distance}
          </h2>
          <p id={leadId}>{ask.name}</p>
          <div className="closure-choices">
            <button type="button" ref={rerouteRef} className="primary" onClick={onReroute}>
              {REROUTE_AROUND_IT}
            </button>
            <button type="button" className="secondary" onClick={onKeep}>
              {KEEP_GOING}
            </button>
          </div>
        </>
      )}
    </dialog>
  );
}
