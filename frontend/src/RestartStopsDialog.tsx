/**
 * Restarting a ride part way (Stephen 2026-10-24: "let people pick the stops that are already done, with the logical
 * defaults selected and continue the rest"): asked once, at the ride's first fix, where it is past a stop. Each stop is
 * a checkbox, the ones behind the rider ticked; Continue rides the rest. The platform's modal <dialog>, as Start ride on
 * a computer's is: Continue takes the focus, Escape is Continue with the ticks as they are.
 */
import { useEffect, useId, useRef, useState } from "react";
import { RESTART_CONTINUE, RESTART_HEADING, RESTART_LEAD, stopWords, type RestartStop } from "./lib/rideStops.ts";

export function RestartStopsDialog({ stops, onContinue }: { stops: RestartStop[] | null; onContinue: (done: ReadonlySet<number>) => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const continueRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const leadId = useId();
  const [done, setDone] = useState<ReadonlySet<number>>(new Set());
  const open = stops !== null;
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      setDone(new Set(stops.filter((s) => s.passed).map((s) => s.index)));
      dialog.showModal?.();
      continueRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
    }
  }, [open, stops]);
  const toggle = (index: number, on: boolean) =>
    setDone((before) => {
      const next = new Set(before);
      if (on) next.add(index);
      else next.delete(index);
      return next;
    });
  return (
    <dialog
      ref={dialogRef}
      className="start-computer-dialog restart-stops-dialog"
      aria-labelledby={headingId}
      aria-describedby={leadId}
      onCancel={(event) => {
        event.preventDefault();
        onContinue(done);
      }}
    >
      {stops && (
        <>
          <h2 id={headingId}>{RESTART_HEADING}</h2>
          <p id={leadId}>{RESTART_LEAD}</p>
          <ul className="restart-stops">
            {stops.map((stop) => (
              <li key={stop.index}>
                <label>
                  <input type="checkbox" checked={done.has(stop.index)} onChange={(event) => toggle(stop.index, event.target.checked)} />
                  {stopWords(stop)}
                </label>
              </li>
            ))}
          </ul>
          <div className="closure-choices">
            <button type="button" ref={continueRef} className="primary" onClick={() => onContinue(done)}>
              {RESTART_CONTINUE}
            </button>
          </div>
        </>
      )}
    </dialog>
  );
}
