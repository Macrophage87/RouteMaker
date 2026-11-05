/**
 * Stop by stop on the ride screen (Stephen, 2026-11-02): the train or bus taken after the line, its way, the stop to get
 * off at and the stops left (lib/onBoard.ts), once on board (waiting, the line's end words say the boarding): the
 * stops still ahead, the next one marked, the last one "get off". Plain text that changes in place; the next stop
 * and the stop to get off are said through the ride's outputs, never by this card.
 */
import { Fragment, useEffect, useState } from "react";
import { boardingGroups, laterDepartureText, lineBadge, liveForBoarding, liveNextText, moreStopsText, type LiveTrain, nextDepartureText, onBoardCardRows, onBoardSecondsLeft, onBoardSecondsTo, stopsLeftText, type OnBoardLeg, type OnBoardState } from "./lib/onBoard.ts";
import { arrivalClock } from "./lib/arrival.ts";
import { formatDuration } from "./lib/format.ts";
import { formatDurationSpoken } from "./lib/spokenFigures.ts";
import { t } from "./lib/i18n.ts";
import { requestStationTimes, TIMES_TTL_MS } from "./lib/stationTimes.ts";

export function OnBoardCard({ leg, state }: { leg: OnBoardLeg; state: OnBoardState }) {
  const off = leg.stops[leg.stops.length - 1].name;
  // The way, unless it is the stop to get off at ("toward Shady Grove" then "Get off at Shady Grove" says it twice).
  const way = leg.toward && leg.toward !== off ? t("{line} toward {place}", { line: leg.line, place: leg.toward }) : leg.line;
  // The next few stops and the stop to get off, each with its place in the leg, for its time (compact at 320 px).
  const { rows, hidden } = onBoardCardRows(leg, state);
  // The time left kept current between stops (the timetable's run, lib/onBoard.ts onBoardSecondsLeft).
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, []);
  const left = onBoardSecondsLeft(leg, state, now);
  return (
    <div className="onboard">
      <p className="cue-then onboard-way">{way}</p>
      <p className="cue-text">{t("Get off at {name}", { name: off })}</p>
      {/* "3 stops left · 12 min" (Stephen, 2026-11-04: "When on transit, put the approximate time left to arrival"),
          heard as "3 stops left, about 12 minutes". The arrival clock is the stop to get off's row's, not repeated here
          unlabelled beside "Trip ends about" (the UI review, 2026-11-05). */}
      <p className="cue-then onboard-left">
        {stopsLeftText(leg, state)}
        {left !== null && (
          <>
            <span aria-hidden="true"> · {formatDuration(left)}</span>
            <span className="visually-hidden">, {t("about")} {formatDurationSpoken(left)}</span>
          </>
        )}
      </p>
      {/* The whole trip's end, from the plan's times after the stop (the walk, the ride after the train). */}
      {left !== null && leg.afterS != null && leg.afterS > 0 && <p className="cue-then onboard-trip-end">{t("Trip ends about {time}", { time: arrivalClock(now, left + leg.afterS) })}</p>}
      <ol className="onboard-stops" aria-label={t("Stops ahead")}>
        {rows.map((row, i) => (
          <Fragment key={`${i}-${row.name}`}>
            {row.off && hidden > 0 && (
              <li className="onboard-more">
                <span aria-hidden="true">…</span>
                <span className="visually-hidden">{moreStopsText(hidden)}</span>
              </li>
            )}
            <li className={row.next ? "onboard-next" : row.off ? "onboard-off" : undefined}>
              <span className="onboard-name">
                {row.name}
                {row.next && !row.off && <span className="onboard-mark"> · {t("next")}</span>}
                {row.off && <span className="onboard-mark"> · {row.next ? t("next, get off") : t("get off")}</span>}
              </span>
              {/* Each stop ahead's clock time (Stephen, 2026-11-04: "the etas for each intermediate station"). */}
              {left !== null && row.index > state.at && <StopClock seconds={onBoardSecondsTo(leg, state, now, row.index) ?? 0} nowMs={now} />}
            </li>
          </Fragment>
        ))}
      </ol>
    </div>
  );
}

/** A stop's clock time at the row's end: "5:31 PM", heard as "arriving about 5:31 PM". */
function StopClock({ seconds, nowMs }: { seconds: number; nowMs: number }) {
  return (
    <span className="onboard-eta">
      <span className="visually-hidden">{t(", arriving about")} </span>
      {arrivalClock(nowMs, seconds)}
    </span>
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
    if (!departure && leg.bus) return;
    const timer = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, [departure, leg.bus]);
  // WMATA's live next trains at the boarding station, read again every TIMES_TTL_MS while waiting (Stephen,
  // 2026-11-03: "Show the next train though"); none for a bus or another system, which keep the plan's times.
  const [live, setLive] = useState<{ trains: readonly LiveTrain[]; asOf: string | null }>({ trains: [], asOf: null });
  const at = leg.stops[0]?.point;
  useEffect(() => {
    if (leg.bus || !at) return;
    let gone = false;
    // A failed read keeps the last good one, which counts down until it is too old (liveForBoarding).
    const read = () =>
      void requestStationTimes(at).then((times) => {
        if (!gone && times?.live) setLive({ trains: times.live.trains, asOf: times.live.as_of });
      });
    // Not while the page is hidden (a phone in a pocket on the platform): nothing reads the answers till it shows.
    const shown = () => typeof document === "undefined" || document.visibilityState !== "hidden";
    const readShown = () => {
      if (shown()) read();
    };
    readShown();
    // Just past the cache's life, so each read is a new one.
    const timer = window.setInterval(readShown, TIMES_TTL_MS + 1_000);
    document.addEventListener("visibilitychange", readShown);
    return () => {
      gone = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", readShown);
    };
  }, [leg.bus, at?.[0], at?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps -- the station's place
  const groups = boardingGroups(leg.trains?.length ? leg.trains : [{ line: leg.line, toward: leg.toward }], off);
  // The next two trains that make the ride, each named by its line; else the plan's times.
  const [first, second] = liveForBoarding(live.trains, groups, leg.stops, { asOf: live.asOf, nowMs: now });
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

/**
 * One live train: its line's badge and when ("[Orange] 3 min"). Its end is left out (Stephen, 2026-11-03: "the
 * destinations twice is redundant"): the list above says where the trains go, and every train shown goes the
 * rider's way.
 */
function LiveTrainLine({ train }: { train: { line: string; minutes: number } }) {
  return (
    <span className="boarding-live">
      <LineBadges lines={[train.line]} /> {liveNextText(train.minutes)}
    </span>
  );
}
