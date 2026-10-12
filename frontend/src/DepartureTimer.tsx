/**
 * An infrequent departure in the trip's panel (lib/departure.ts): the departure in words, always, and
 * when cutting it close a countdown to it with the time to spare. The countdown is plain text that
 * changes each second, not a live region, so a screen reader is never talked over; the milestones
 * (10, 5 and 2 minutes) and a miss are said through `announce`, the page's one status line. A miss
 * asks for a new plan (`onMissed`), which takes the next departure. No animation: the numbers change.
 */
import { useEffect, useRef, useState } from "react";
import type { TransitDeparture } from "./lib/api.ts";
import { countdown, departureText, milestone, milestoneSaid, missedSaid, mmss } from "./lib/departure.ts";

export function DepartureTimer({
  departure,
  announce,
  onMissed,
  now = () => Date.now(),
}: {
  departure: TransitDeparture;
  announce?: (text: string) => void;
  onMissed?: () => void;
  now?: () => number;
}) {
  const [at, setAt] = useState(now);
  const last = useRef<number | null>(null);
  const missedOnce = useRef(false);
  useEffect(() => {
    last.current = null;
    missedOnce.current = false;
    const tick = () => setAt(now());
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [departure.departs_at, departure.planned_at]);
  const state = countdown(departure, at);
  useEffect(() => {
    const before = last.current;
    last.current = state.toDepartS;
    if (state.missed && !missedOnce.current) {
      missedOnce.current = true;
      announce?.(missedSaid(departure));
      onMissed?.();
      return;
    }
    if (before === null || !state.close) return;
    const mark = milestone(before, state.toDepartS);
    if (mark !== null) announce?.(milestoneSaid(departure, mark));
  }, [at]);
  return (
    <div className="departure">
      <p className="departure-text">
        <strong>{departureText(departure)}</strong>
      </p>
      {state.close && !state.missed && (
        <p className="departure-timer notice">
          Cutting it close. Departs in <span className="departure-count">{mmss(state.toDepartS)}</span>; time to spare{" "}
          <span className="departure-count">{mmss(state.spareS)}</span>.
        </p>
      )}
      {state.missed && <p className="departure-timer notice">{missedSaid(departure)}</p>}
    </div>
  );
}
