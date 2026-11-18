/**
 * The "?" sheet of Plan's keyboard shortcuts (lib/planKeys.ts): the keys and what each does, and the switch that
 * turns the single-key ones off (WCAG 2.1.4). Opened by "?" or by Keyboard shortcuts in Points' Tips. The platform's
 * modal <dialog>: Close takes the focus, Escape closes, and the focus goes back where it was.
 */
import { useEffect, useId, useRef } from "react";
import { t } from "./lib/i18n.ts";
import { PLAN_KEYS_SWITCH, PLAN_KEYS_SWITCH_HINT, PLAN_KEYS_TITLE, PLAN_KEY_ROWS } from "./lib/planKeys.ts";

export function PlanKeysDialog({ open, on, onSwitch, onClose }: { open: boolean; on: boolean; onSwitch: (on: boolean) => void; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const hintId = useId();
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal?.();
      closeRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
    }
  }, [open]);
  return (
    <dialog
      ref={dialogRef}
      className="ask-dialog plan-keys-dialog"
      aria-labelledby={headingId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      {open && (
        <>
          <h2 id={headingId}>{PLAN_KEYS_TITLE}</h2>
          <dl className="plan-keys">
            {PLAN_KEY_ROWS.map((row) => (
              <div key={row.what}>
                <dt>{row.keys.map((key) => (key === "–" ? <span key={key}> {t("to")} </span> : <kbd key={key}>{key}</kbd>))}</dt>
                <dd>{row.what}</dd>
              </div>
            ))}
          </dl>
          <label className="plan-keys-switch">
            <input type="checkbox" checked={on} aria-describedby={hintId} onChange={(event) => onSwitch(event.target.checked)} />
            {PLAN_KEYS_SWITCH}
          </label>
          <p id={hintId} className="hint">
            {PLAN_KEYS_SWITCH_HINT}
          </p>
          <div className="closure-choices">
            <button type="button" ref={closeRef} className="primary" onClick={onClose}>
              {t("Close")}
            </button>
          </div>
        </>
      )}
    </dialog>
  );
}
