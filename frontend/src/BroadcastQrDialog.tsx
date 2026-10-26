/**
 * Broadcast's QR code (lib/broadcastQr.ts): the platform's modal <dialog>, as Start on a computer's is. The code, big
 * and on white for a camera; Start ride (held from beside Start, before the ride) and Close. Escape closes; on close
 * the focus goes back where it was.
 */
import { useEffect, useId, useMemo, useRef } from "react";
import { BROADCAST_QR_CLOSE, BROADCAST_QR_HEADING, BROADCAST_QR_LEAD, BROADCAST_QR_NAME, BROADCAST_QR_START, qrPath } from "./lib/broadcastQr.ts";

export function BroadcastQrDialog({ ask, onClose }: { ask: { link: string; start: (() => void) | null } | null; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const firstRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const leadId = useId();
  const open = ask !== null;
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal?.();
      firstRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
    }
  }, [open]);
  const code = useMemo(() => (ask ? qrPath(ask.link) : null), [ask?.link]);
  return (
    <dialog
      ref={dialogRef}
      className="ask-dialog broadcast-qr-dialog"
      aria-labelledby={headingId}
      aria-describedby={leadId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      {ask && code && (
        <>
          <h2 id={headingId}>{BROADCAST_QR_HEADING}</h2>
          <svg className="broadcast-qr" viewBox={`0 0 ${code.size} ${code.size}`} role="img" aria-label={BROADCAST_QR_NAME} shapeRendering="crispEdges">
            <rect width={code.size} height={code.size} fill="#ffffff" />
            <path d={code.d} fill="#000000" />
          </svg>
          <p id={leadId}>{BROADCAST_QR_LEAD}</p>
          <div className="closure-choices">
            {ask.start && (
              <button
                type="button"
                ref={firstRef}
                className="primary"
                onClick={() => {
                  const start = ask.start;
                  onClose();
                  start?.();
                }}
              >
                {BROADCAST_QR_START}
              </button>
            )}
            <button type="button" ref={ask.start ? undefined : firstRef} className="secondary" onClick={onClose}>
              {BROADCAST_QR_CLOSE}
            </button>
          </div>
        </>
      )}
    </dialog>
  );
}
