/**
 * A full account's question (the owner, 2026-11-07: "at 200 routes, then propose deleting the route that has the
 * longest time since last open or creation"): a save with nothing archived to make room from names the route
 * unopened longest and asks before deleting it. Cancel is first and takes the focus, since a delete cannot be undone;
 * Escape is Cancel; on close the focus goes back where it was.
 */
import { useEffect, useId, useRef } from "react";
import { t } from "./lib/i18n.ts";
import { FULL_DELETE, FULL_HEADING, fullAsk, type RoomProposal } from "./lib/savedRoutes.ts";

export function FullAccountDialog({ propose, onDelete, onCancel }: { propose: RoomProposal | null; onDelete: () => void; onCancel: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const leadId = useId();
  const open = propose !== null;
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal?.();
      cancelRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
    }
  }, [open]);
  return (
    <dialog
      ref={dialogRef}
      className="ask-dialog full-account-dialog"
      aria-labelledby={headingId}
      aria-describedby={leadId}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
    >
      {propose && (
        <>
          <h2 id={headingId}>{FULL_HEADING}</h2>
          <p id={leadId}>{fullAsk(propose)}</p>
          <div className="closure-choices">
            <button type="button" ref={cancelRef} className="primary" onClick={onCancel}>
              {t("Cancel")}
            </button>
            <button type="button" className="secondary" onClick={onDelete}>
              {FULL_DELETE}
            </button>
          </div>
        </>
      )}
    </dialog>
  );
}
