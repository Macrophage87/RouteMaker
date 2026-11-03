/**
 * Stop by stop on the ride screen (Stephen, 2026-11-02): the train or bus taken after the line, its way, the stop to get
 * off at and the stops left (lib/onBoard.ts), once on board (waiting, the line's end words say the boarding): the
 * stops still ahead, the next one marked, the last one "get off". Plain text that changes in place; the next stop
 * and the stop to get off are said through the ride's outputs, never by this card.
 */
import { useEffect, useState } from "react";
import { boardingGroups, laterDepartureText, lineBadge, liveForBoarding, liveNextText, type LiveTrain, nextDepartureText, onBoardRows, stopsLeftText, type OnBoardLeg, type OnBoardState } from "./lib/onBoard.ts";
import { t } from "./lib/i18n.ts";
import { requestStationTimes, TIMES_TTL_MS } from "./lib/stationTimes.ts";

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
 * destination, next train", "make it more table or list than a wall of text", "Put the acceptable destination
 * options", "You can use colors to make it compact"): the trains that will do, each as its line's coloured badge and
 * where it is signed to; then the stop to get off, the next departure and the one after it, one row each.
 */
export function BoardingCard({
  leg,
  departure,
  note,
}: {
  leg: OnBoardLeg;
  departure: { departs: string; departs_at: string; next?: string | null; next_at?: string | null } | null;
  /** What comes first, short: "About 4 min into the station by the elevator." */
  note?: string | null;
}) {
  const off = leg.stops[leg.stops.length - 1].name;
  // The minutes to a timed departure, kept current.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!departure) return;
    const timer = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, [departure]);
  // WMATA's live next trains at the boarding station, read again every TIMES_TTL_MS while waiting (Stephen,
  // 2026-11-03: "Show the next train though"); none for a bus or another system, which keep the plan's times.
  const [live, setLive] = useState<readonly LiveTrain[]>([]);
  const at = leg.stops[0]?.point;
  useEffect(() => {
    if (leg.bus || !at) return;
    let gone = false;
    const read = () =>
      void requestStationTimes(at).then((times) => {
        if (!gone) setLive(times?.live?.trains ?? []);
      });
    read();
    const timer = window.setInterval(read, TIMES_TTL_MS);
    return () => {
      gone = true;
      window.clearInterval(timer);
    };
  }, [leg.bus, at?.[0], at?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps -- the station's place
  const groups = boardingGroups(leg.trains?.length ? leg.trains : [{ line: leg.line, toward: leg.toward }], off);
  // The next two trains that make the ride, each named by its line and end; else the plan's times.
  const [first, second] = liveForBoarding(live, groups, leg.stops);
  const next = nextDepartureText(leg, departure, now);
  const later = laterDepartureText(departure, now);
  return (
    <div className="boarding">
      {note && <p className="cue-then boarding-note">{note}</p>}
      {/* One row per end station, its lines' badges first (Stephen, 2026-11-03: "Like orange/silver new Carrollton,
          blue/silver Downtown Largo"). */}
      <ul className="boarding-trains">
        {groups.map(({ lines, toward }) => (
          <li key={`${lines.join("|")}>${toward ?? ""}`}>
            <LineBadges lines={lines} />
            {toward && (
              <>
                <span className="visually-hidden"> {t("toward")} </span>
                <span className="boarding-toward">{toward}</span>
              </>
            )}
          </li>
        ))}
      </ul>
      <dl className="boarding-rows">
        <dt>{t("Get off")}</dt>
        <dd>{off}</dd>
        {first ? (
          <>
            <dt>{t("Next train")}</dt>
            <dd>
              <LiveTrainLine train={first} />
            </dd>
            {second && (
              <>
                <dt>{t("After that")}</dt>
                <dd>
                  <LiveTrainLine train={second} />
                </dd>
              </>
            )}
          </>
        ) : (
          <>
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
          </>
        )}
        {leg.rack && (
          <>
            <dt>{t("Bike")}</dt>
            <dd>{t("Front rack")}</dd>
          </>
        )}
      </dl>
    </div>
  );
}

/** Lines as coloured badges ("Orange"), each read whole by a screen reader ("Orange Line"). */
function LineBadges({ lines }: { lines: readonly string[] }) {
  return (
    <>
      {lines.map((line, i) => {
        const badge = lineBadge(line);
        const short = badge ? line.replace(/ Line$/, "") : line;
        return (
          <span key={line}>
            {/* Compact: a coloured badge says "Orange", its colour the rest; a screen reader hears the full name. */}
            <span className={badge ? "line-badge" : "line-badge line-badge-plain"} style={badge ?? undefined} aria-hidden="true">
              {short}
            </span>
            <span className="visually-hidden">
              {i > 0 ? ", " : ""}
              {line}
            </span>
          </span>
        );
      })}
    </>
  );
}

/** One live train: its line's badge, its end and when ("[Orange] New Carrollton, in 3 min, live"). */
function LiveTrainLine({ train }: { train: { line: string; toward: string; minutes: number } }) {
  return (
    <span className="boarding-live">
      <LineBadges lines={[train.line]} /> <span className="visually-hidden">{t("toward")} </span>
      {train.toward}, {liveNextText(train.minutes)}
    </span>
  );
}
