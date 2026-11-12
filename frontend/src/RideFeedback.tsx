/**
 * The ride summary's two lines that learn from the ride (lib/rideFeedback.ts; the 2026-11-12 backlog, item 7, the
 * owner's "Both lines"): "Anything feel different from its rating?" and, after Road closed presses, the offer to send
 * them for review. Shown by RideSummaryCard.tsx under its figures.
 *
 * Their status lines are mounted empty and filled when something happens (a look-up, a send), so a screen reader says
 * them; the card's own "Ride ended." stays with the page's polite region (review F6).
 */
import { Fragment, useEffect, useId, useRef, useState } from "react";
import { t } from "./lib/i18n.ts";
import {
  CLOSED_NOT_SENT,
  CLOSED_OFFER,
  CLOSED_SEND,
  CLOSED_SENDING,
  CLOSED_SENT,
  CLOSED_WHAT,
  FELT_DIFFERENT,
  FELT_PICK,
  roadAt,
  roadStep,
  sendClosedSpots,
  type FeltStretch,
} from "./lib/rideFeedback.ts";
import type { LonLat } from "./lib/geo.ts";
import type { SegmentInfo } from "./lib/roadInfo.ts";
import { csrfFromCookie } from "./lib/stressEditor.ts";
import { SuggestQuick } from "./SuggestQuick.tsx";

/** Said where a street's road cannot be looked up just now. */
const FELT_LOOKUP_FAILED = t("That road can't be looked up right now. Try again shortly.");

/**
 * "Anything feel different from its rating?" (lib/rideFeedback.ts): one line; pressed, the streets ridden, longest
 * first; a street pressed, the road panel's short suggestion form on its road. Nothing is sent until its Send.
 */
export function FeltDifferent({ origin, stretches }: { origin: string; stretches: FeltStretch[] }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<{ stretch: FeltStretch; info: SegmentInfo } | null>(null);
  const [looking, setLooking] = useState<FeltStretch | null>(null);
  const [said, setSaid] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const headingId = useId();
  useEffect(() => {
    if (open && !form) heading.current?.focus();
  }, [open, form]);
  const pick = (stretch: FeltStretch) => {
    if (looking) return;
    setLooking(stretch);
    setSaid("");
    void roadAt(origin, stretch.point).then((info) => {
      setLooking(null);
      if (info && roadStep(info)) setForm({ stretch, info });
      else setSaid(FELT_LOOKUP_FAILED);
    });
  };
  if (!open) {
    return (
      <p className="ride-summary-felt">
        <button type="button" className="link" onClick={() => setOpen(true)}>
          {FELT_DIFFERENT}
        </button>
      </p>
    );
  }
  if (form) {
    const { info, stretch } = form;
    return (
      <SuggestQuick
        origin={origin}
        wayId={info.osm_way_id as number}
        title={info.title || stretch.street || ""}
        current={roadStep(info)}
        point={info.on_way ?? stretch.point}
        halfSteps={info.half_steps === true}
        fromRide
        onClose={() => setForm(null)}
      />
    );
  }
  return (
    <section className="ride-summary-felt" aria-labelledby={headingId}>
      <h3 id={headingId} ref={heading} tabIndex={-1}>
        {FELT_PICK}
      </h3>
      <ul className="ride-summary-felt-list">
        {stretches.map((s, n) => (
          <li key={n}>
            <button type="button" className="secondary" aria-disabled={looking ? true : undefined} onClick={() => pick(s)}>
              {/* Each part kept whole, the line breaking only between them. */}
              {s.label.split(" · ").map((part, i) => (
                <Fragment key={part}>
                  {i > 0 && " · "}
                  <span>{part}</span>
                </Fragment>
              ))}
            </button>
          </li>
        ))}
      </ul>
      <p role="status" className="hint">
        {looking ? t("Looking up the road…") : said}
      </p>
    </section>
  );
}

/**
 * Road closed presses (lib/rideFeedback.ts): offered for review, opt in, each ride. Sent: how many, in the line's place.
 */
export function ClosedOffer({ origin, spots }: { origin: string; spots: LonLat[] }) {
  // The spots still to send: all of them, then those a send could not (a retry never sends one twice).
  const [left, setLeft] = useState(spots);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(0);
  const [tried, setTried] = useState(false);
  const line = useRef<HTMLParagraphElement>(null);
  const done = tried && left.length === 0;
  useEffect(() => {
    // All sent: the Send button the focus was on goes, so the focus goes to the line that says so.
    if (done && (document.activeElement === null || document.activeElement === document.body)) line.current?.focus();
  }, [done]);
  const send = () => {
    if (sending || left.length === 0) return;
    setSending(true);
    void sendClosedSpots(origin, left, () => csrfFromCookie(document.cookie)).then((outcome) => {
      setSending(false);
      setTried(true);
      setSent((n) => n + outcome.sent);
      setLeft(outcome.left);
    });
  };
  const said = tried ? [sent > 0 ? CLOSED_SENT(sent) : "", left.length > 0 ? CLOSED_NOT_SENT : ""].filter(Boolean).join(" ") : "";
  return (
    <div className="ride-summary-favorite ride-summary-closed">
      <p ref={line} tabIndex={done ? -1 : undefined}>
        {tried ? null : CLOSED_OFFER(spots.length)} <span className="hint">{tried ? null : CLOSED_WHAT}</span>
        <span role="status">{said}</span>
      </p>
      {!done && (
        <button type="button" className="secondary" aria-disabled={sending || undefined} onClick={sending ? undefined : send}>
          {sending ? CLOSED_SENDING : CLOSED_SEND}
        </button>
      )}
    </div>
  );
}
