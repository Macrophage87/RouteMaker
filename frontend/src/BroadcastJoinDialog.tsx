/**
 * Joining a broadcast (lib/broadcastJoin.ts): one big sheet over the ride, the platform's modal <dialog> as Broadcast's
 * QR code is. The route's name and one line (distance · time), then Download GPX, Send to Garmin and Send to Wahoo
 * (where connected) and Just ride. Each does what the GPX sheet's own button does and says what happened here, in the
 * sheet's status region, without the voice (the ride's cues keep it). Escape, a tap outside, Just ride or a screen left
 * alone (lib/idleRecentre.ts) closes it; on close the focus goes back where it was.
 */
import { useEffect, useId, useRef, useState } from "react";
import type { Made, Said } from "./GpxPanel.tsx";
import { JOIN_JUST_RIDE, JOIN_OFFER, type JoinAction } from "./lib/broadcastJoin.ts";
import { IDLE_CLOSE_ATTR } from "./lib/idleRecentre.ts";
import { t } from "./lib/i18n.ts";
import { SEND_LABEL as GARMIN_SEND_LABEL } from "./lib/sendToGarmin.ts";
import { SEND_LABEL as WAHOO_SEND_LABEL } from "./lib/wahooLink.ts";

export interface JoinAsk {
  title: string;
  line: string;
  actions: JoinAction[];
}

const LABEL: Record<JoinAction, () => string> = {
  gpx: () => t("Download GPX"),
  garmin: () => GARMIN_SEND_LABEL,
  wahoo: () => WAHOO_SEND_LABEL,
};

export function BroadcastJoinDialog({ ask, onAction, onClose }: { ask: JoinAsk | null; onAction: (action: JoinAction, said: Said) => void; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const firstRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const leadId = useId();
  const open = ask !== null;
  const [said, setSaid] = useState<{ text: string; count: number } | null>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setSaid(null);
      opener.current = document.activeElement;
      dialog.showModal?.();
      firstRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
    }
  }, [open]);
  const say: Said = (made: Made) => {
    const text = typeof made === "string" ? made : made.line;
    setSaid((s) => ({ text, count: (s?.count ?? 0) + 1 }));
  };
  return (
    <dialog
      ref={dialogRef}
      className="ask-dialog broadcast-join-dialog"
      aria-labelledby={headingId}
      aria-describedby={leadId}
      {...{ [IDLE_CLOSE_ATTR]: "" }}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      // Closed by the platform without a cancel (a phone's back gesture, a screen left alone): the page closes it too.
      onClose={() => {
        if (open) onClose();
      }}
      // A tap on the backdrop lands on the dialog itself (its content fills it): a tap outside closes it.
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      {ask && (
        <div className="broadcast-join">
          <h2 id={headingId}>{ask.title}</h2>
          <p className="broadcast-join-line">{ask.line}</p>
          <p id={leadId} className="visually-hidden">
            {JOIN_OFFER}
          </p>
          <div className="broadcast-join-actions">
            {ask.actions.map((action, i) => (
              <button key={action} type="button" ref={i === 0 ? firstRef : undefined} className="primary" onClick={() => onAction(action, say)}>
                {LABEL[action]()}
              </button>
            ))}
            <button type="button" className="secondary" onClick={onClose}>
              {JOIN_JUST_RIDE}
            </button>
          </div>
          <div role="status" aria-live="polite">
            {said && (
              <p key={said.count} className="hint broadcast-join-said">
                {said.text}
              </p>
            )}
          </div>
        </div>
      )}
    </dialog>
  );
}
