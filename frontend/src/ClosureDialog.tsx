/**
 * The major closure warning (v0.7.0 plan, "GPX export as close to identical as possible, closure warning
 * first", and its correction): a modal dialog, not a toast, when a kept route runs along closures in force now.
 * "This route goes through 2 closures", each named in one line, and three choices: Reroute around them ("it" for
 * one; the default), Ride it anyway (or Download or Save anyway), and Cancel. The park-wide notices, which are not
 * closures on the route, wait behind "Park notices (N)" (P11). The platform's <dialog> opened with
 * showModal makes the page behind inert; the focus starts on the heading so a screen reader reads the list;
 * Escape is Cancel; on close the focus goes back where it was.
 */
import { useEffect, useId, useRef } from "react";
import type { ClosureNotice } from "./lib/closureMap.ts";
import { CANCEL_LABEL, anywayLabel, closureHeading, closureLead, parkNoticesSummary, rerouteLabel, type CheckFor, type Closure } from "./lib/closureCheck.ts";
import { t } from "./lib/i18n.ts";

export interface ClosureAsk {
  why: CheckFor;
  closures: Closure[];
  unchecked: string | null;
  /** v0.7.0: "Check before you go" (NPS park alerts, advisories that could not be placed), shown under the list. */
  notices?: ClosureNotice[];
}

export function ClosureDialog({ ask, onReroute, onAnyway, onCancel }: { ask: ClosureAsk | null; onReroute: () => void; onAnyway: () => void; onCancel: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  // The description is the lead line only (review F11); the list is read from the heading, where the focus starts.
  const leadId = useId();
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
      aria-describedby={leadId}
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
          <div>
            <p id={leadId}>{closureLead(ask.why)}</p>
            <ul role="list" className="closure-list">
              {ask.closures.map((c) => (
                <li key={c.id}>
                  {c.text}
                  {/* v0.7.0: the DC sources' closures name their source, linked, as the map's card does. */}
                  {c.source_name && (
                    <>
                      {" "}
                      {c.url ? (
                        <a href={c.url} target="_blank" rel="noopener noreferrer">
                          {t("Source: {source}", { source: c.source_name })}
                        </a>
                      ) : (
                        t("Source: {source}", { source: c.source_name })
                      )}
                      .
                    </>
                  )}
                </li>
              ))}
            </ul>
            {/* Park-wide notices are not closures on the route: behind a disclosure, the list above them (P11). */}
            {ask.notices && ask.notices.length > 0 && (
              <details className="closure-notices">
                <summary className="closure-notices-heading">{parkNoticesSummary(ask.notices.length)}</summary>
                <ul role="list" className="closure-list">
                  {ask.notices.map((n) => (
                    <li key={n.id}>
                      {n.area_name ? `${n.area_name}: ` : ""}
                      {n.title}.{" "}
                      {n.url ? (
                        <a href={n.url} target="_blank" rel="noopener noreferrer">
                          {n.source_name}
                        </a>
                      ) : (
                        n.source_name
                      )}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {ask.unchecked && <p className="hint">{ask.unchecked}</p>}
          </div>
          <div className="closure-choices">
            <button type="button" className="primary closure-reroute" onClick={onReroute}>
              {rerouteLabel(ask.closures.length)}
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
