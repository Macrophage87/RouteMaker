/**
 * Stop by stop on the ride screen (Stephen, 2026-11-02): the train or bus taken after the line, its way, the stop to get
 * off at and the stops left (lib/onBoard.ts), once on board (waiting, the line's end words say the boarding): the
 * stops still ahead, the next one marked, the last one "get off". Plain text that changes in place; the next stop
 * and the stop to get off are said through the ride's outputs, never by this card.
 */
import { useEffect, useState } from "react";
import { laterDepartureText, nextDepartureText, onBoardRows, stopsLeftText, type OnBoardLeg, type OnBoardState } from "./lib/onBoard.ts";
import { t } from "./lib/i18n.ts";

export function OnBoardCard({ leg, state }: { leg: OnBoardLeg; state: OnBoardState }) {
  const off = leg.stops[leg.stops.length - 1].name;
  // The way, unless it is the stop to get off at ("toward Shady Grove" then "Get off at Shady Grove" says it twice).
  const way = leg.toward && leg.toward !== off ? t("{line} toward {place}", { line: leg.line, place: leg.toward }) : leg.line;
  const rows = onBoardRows(leg, state).filter((row, i) => i >= state.at || row.off);
  return (
    <div className="onboard">
      <p className="cue-then onboard-way">{way}</p>
      <p className="cue-text">{t("Get off at {name}", { name: off })}</p>
      <p className="cue-then">{stopsLeftText(leg, state)}</p>
      <ol className="onboard-stops" aria-label={t("Stops ahead")}>
        {rows.map((row, i) => (
          <li key={`${i}-${row.name}`} className={row.next ? "onboard-next" : row.off ? "onboard-off" : undefined}>
            <span>{row.name}</span>
            {row.next && !row.off && <span className="onboard-mark"> · {t("next")}</span>}
            {row.off && <span className="onboard-mark"> · {row.next ? t("next, get off") : t("get off")}</span>}
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * Waiting to board (Stephen, 2026-11-03: "Make the screen less verbose for transit", "Line, final destination, actual
 * destination, next train", "make it more table or list than a wall of text"): the line, its way, the stop to get off
 * and the next departure, one row each, in place of the plan's boarding sentence.
 */
export function BoardingCard({ leg, departure }: { leg: OnBoardLeg; departure: { departs: string; departs_at: string; next?: string | null; next_at?: string | null } | null }) {
  const off = leg.stops[leg.stops.length - 1].name;
  // The minutes to a timed departure, kept current.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!departure) return;
    const timer = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, [departure]);
  const next = nextDepartureText(leg, departure, now);
  const later = laterDepartureText(departure, now);
  return (
    <dl className="boarding">
      <dt>{t("Line")}</dt>
      <dd>{leg.line}</dd>
      {leg.toward && leg.toward !== off && (
        <>
          <dt>{t("Toward")}</dt>
          <dd>{leg.toward}</dd>
        </>
      )}
      <dt>{t("Get off")}</dt>
      <dd>{off}</dd>
      {next && (
        <>
          <dt>{leg.bus ? t("Next bus") : t("Next train")}</dt>
          <dd>{next}</dd>
        </>
      )}
      {later && (
        <>
          <dt>{t("After that")}</dt>
          <dd>{later}</dd>
        </>
      )}
    </dl>
  );
}
