/**
 * Joining a broadcast (lib/broadcastJoin.ts): one big sheet over the ride, the platform's modal <dialog> as Broadcast's
 * QR code is. The route's name and one line (distance · time), then Download GPX, Send to Garmin and Send to Wahoo
 * (where connected) and Just ride. Each does what the GPX sheet's own button does and says what happened here, in the
 * sheet's status region, without the voice (the ride's cues keep it). Escape, a tap outside, Just ride or a screen left
 * alone (lib/idleRecentre.ts) closes it; on close the focus goes back where it was.
 *
 * One screen, not two (Stephen 2026-10-30: "put the location consent and the download route on the same screen when
 * joining a ride"): where the ride also asks "Show me as a dot?", RideGroup's question carries the route and its
 * buttons (JoinOffer) and this sheet is not shown; it stands alone only where nothing is asked.
 */
import { useEffect, useId, useRef, useState, type ReactNode, type Ref } from "react";
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

/**
 * The route's buttons and what they did, the sheet's own and the dot question's (RideGroup.tsx): each press says its
 * outcome in a polite status region, without the voice. Mounted afresh with each ask, so nothing said is left over.
 */
export function JoinOffer({ ask, onAction, firstRef, children }: { ask: JoinAsk; onAction: (action: JoinAction, said: Said) => void; firstRef?: Ref<HTMLButtonElement>; children?: ReactNode }) {
  const [said, setSaid] = useState<{ text: string; count: number } | null>(null);
  const say: Said = (made: Made) => {
    const text = typeof made === "string" ? made : made.line;
    setSaid((s) => ({ text, count: (s?.count ?? 0) + 1 }));
  };
  return (
    <>
      <div className="broadcast-join-actions">
        {ask.actions.map((action, i) => (
          <button key={action} type="button" ref={i === 0 ? firstRef : undefined} className="primary" onClick={() => onAction(action, say)}>
            {LABEL[action]()}
          </button>
        ))}
        {children}
      </div>
      <div role="status" aria-live="polite">
        {said && (
          <p key={said.count} className="hint broadcast-join-said">
            {said.text}
          </p>
        )}
      </div>
    </>
  );
}

export function BroadcastJoinDialog({ ask, onAction, onClose }: { ask: JoinAsk | null; onAction: (action: JoinAction, said: Said) => void; onClose: () => void }) {
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
          <JoinOffer ask={ask} onAction={onAction} firstRef={firstRef}>
            <button type="button" className="secondary" onClick={onClose}>
              {JOIN_JUST_RIDE}
            </button>
          </JoinOffer>
        </div>
      )}
    </dialog>
  );
}
