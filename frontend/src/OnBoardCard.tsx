/**
 * Stop by stop on the ride screen (Stephen, 2026-11-02): the train or bus taken after the line, its way, the stop to get
 * off at and the stops left (lib/onBoard.ts). Waiting, one line: the line, its way and the stop to get off. On board,
 * the stops still ahead, the next one marked, the last one "get off". Plain text that changes in place; the next stop
 * and the stop to get off are said through the ride's outputs, never by this card.
 */
import { onBoardRows, stopsLeftText, type OnBoardLeg, type OnBoardState } from "./lib/onBoard.ts";
import { t } from "./lib/i18n.ts";

export function OnBoardCard({ leg, state }: { leg: OnBoardLeg; state: OnBoardState | null }) {
  const off = leg.stops[leg.stops.length - 1].name;
  const way = leg.toward ? t("{line} toward {place}", { line: leg.line, place: leg.toward }) : leg.line;
  if (!state || state.boardedAt === null) {
    return (
      <p className="cue-then onboard-waiting">
        {way} · {t("Get off at {name}", { name: off })} · {stopsLeftText(leg, state ?? { at: 0 })}
      </p>
    );
  }
  const rows = onBoardRows(leg, state).filter((row, i) => i >= state.at || row.off);
  return (
    <div className="onboard">
      <p className="cue-then onboard-way">{way}</p>
      <p className="cue-text">{t("Get off at {name}", { name: off })}</p>
      <p className="cue-then">{stopsLeftText(leg, state)}</p>
      <ol className="onboard-stops" aria-label={t("Stops ahead")}>
        {rows.map((row, i) => (
          <li key={`${i}-${row.name}`} className={row.next ? "onboard-next" : row.off ? "onboard-off" : row.passed ? "onboard-passed" : undefined}>
            <span>{row.name}</span>
            {row.next && !row.off && <span className="onboard-mark"> · {t("next")}</span>}
            {row.off && <span className="onboard-mark"> · {row.next ? t("next, get off") : t("get off")}</span>}
          </li>
        ))}
      </ol>
    </div>
  );
}
