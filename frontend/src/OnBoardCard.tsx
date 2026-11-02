/**
 * Stop by stop on the ride screen (Stephen, 2026-11-02): the train or bus taken after the line, its way, the stop to get
 * off at and the stops left (lib/onBoard.ts), once on board (waiting, the line's end words say the boarding): the
 * stops still ahead, the next one marked, the last one "get off". Plain text that changes in place; the next stop
 * and the stop to get off are said through the ride's outputs, never by this card.
 */
import { onBoardRows, stopsLeftText, type OnBoardLeg, type OnBoardState } from "./lib/onBoard.ts";
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
