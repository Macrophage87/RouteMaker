/**
 * The major closure warning (v0.7.0 plan, "GPX export as close to identical as possible, closure warning
 * first", and its correction): a modal dialog, not a toast, when a kept route runs along closures in force now.
 * "This route goes through 2 closures", each named in one line, and three choices: Reroute around them (the
 * default), Ride it anyway (or Download or Save anyway), and Cancel. The platform's <dialog> opened with
 * showModal makes the page behind inert; the focus starts on the heading so a screen reader reads the list;
 * Escape is Cancel; on close the focus goes back where it was.
 */
import { useEffect, useId, useRef } from "react";
import { CANCEL_LABEL, REROUTE_LABEL, anywayLabel, closureHeading, closureLead, type CheckFor, type Closure } from "./lib/closureCheck.ts";

export interface ClosureAsk {
  why: CheckFor;
  closures: Closure[];
  unchecked: string | null;
}

export function ClosureDialog({ ask, onReroute, onAnyway, onCancel }: { ask: ClosureAsk | null; onReroute: () => void; onAnyway: () => void; onCancel: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const listId = useId();
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (ask && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal?.();
      headingRef.current?.focus();
    } else if (!ask && dialog.open) {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
    }
  }, [ask]);
  return (
    <dialog
      ref={dialogRef}
      className="closure-dialog"
      aria-labelledby={headingId}
      aria-describedby={listId}
      onCancel={(event) => {
        // Escape is Cancel; the page decides what closes it.
        event.preventDefault();
        onCancel();
      }}
    >
      {ask && (
        <>
          <h2 id={headingId} ref={headingRef} tabIndex={-1}>
            {closureHeading(ask.closures.length)}
          </h2>
          <div id={listId}>
            <p>{closureLead(ask.why)}</p>
            <ul role="list" className="closure-list">
              {ask.closures.map((c) => (
                <li key={c.id}>{c.text}</li>
              ))}
            </ul>
            {ask.unchecked && <p className="hint">{ask.unchecked}</p>}
          </div>
          <div className="closure-choices">
            <button type="button" className="primary closure-reroute" onClick={onReroute}>
              {REROUTE_LABEL}
            </button>
            <button type="button" className="secondary closure-anyway" onClick={onAnyway}>
              {anywayLabel(ask.why)}
            </button>
            <button type="button" className="secondary closure-cancel" onClick={onCancel}>
              {CANCEL_LABEL}
            </button>
          </div>
        </>
      )}
    </dialog>
  );
}
