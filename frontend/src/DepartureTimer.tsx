/**
 * An infrequent departure in the trip's panel (lib/departure.ts): the departure in words, always, and
 * when cutting it close a countdown to it with the time to spare. The countdown is plain text that
 * changes each second, not a live region, so a screen reader is never talked over; the milestones
 * (10, 5 and 2 minutes) and a miss are said through `announce`, the page's one status line. A miss
 * asks for a new plan (`onMissed`), which takes the next departure. No animation: the numbers change.
 */
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import type { TransitDeparture } from "./lib/api.ts";
import { countdown, departureText, mapLabel, milestone, milestoneSaid, missedSaid, mmss, sourceWord } from "./lib/departure.ts";
import { t } from "./lib/i18n.ts";

/** A translated sentence with its {places} filled by elements, so a language puts the countdown where its grammar wants it. */
function withPlaces(sentence: string, places: Readonly<Record<string, ReactNode>>): ReactNode[] {
  return sentence.split(/\{(\w+)\}/).map((part, i) => <Fragment key={i}>{i % 2 === 1 ? (part in places ? places[part] : `{${part}}`) : part}</Fragment>);
}

export function DepartureTimer({
  departure,
  announce,
  onMissed,
  compact = false,
  noticeOnly = false,
  now = () => Date.now(),
}: {
  departure: TransitDeparture;
  announce?: (text: string) => void;
  onMissed?: () => void;
  /** Go's sheet at its smallest: one line, the map label's words, the same milestones and miss. */
  compact?: boolean;
  /** The ride screen's boarding card shows the departure: here only a close or missed one's notice, its milestones still said. */
  noticeOnly?: boolean;
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
  if (compact) {
    return (
      <p className={state.close || state.missed ? "departure-compact notice" : "departure-compact"}>
        <span className="departure-count">{mapLabel(departure, at)}</span>
      </p>
    );
  }
  if (noticeOnly && !state.close && !state.missed) return null;
  return (
    <div className="departure">
      {!noticeOnly && (
        <p className="departure-text">
          <strong>{departureText(departure)}</strong>
        </p>
      )}
      {state.close && !state.missed && (
        <p className="departure-timer notice">
          {withPlaces(t("Cutting it close. Departs in {count}, {source}; time to spare {spare}."), {
            count: <span className="departure-count">{mmss(state.toDepartS)}</span>,
            source: sourceWord(departure),
            spare: <span className="departure-count">{mmss(state.spareS)}</span>,
          })}
        </p>
      )}
      {state.missed && <p className="departure-timer notice">{missedSaid(departure)}</p>}
    </div>
  );
}
