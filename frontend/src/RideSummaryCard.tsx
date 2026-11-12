/**
 * After End ride (the owner, 2026-10-20: "When ending a ride, perhaps summary stats rather than programming that ride
 * again"): the ride's own figures (lib/rideStats.ts) in one card, with Done and Keep riding. It leads with where, how
 * far and how long ("Union Station · 2.6 mi (4.2 km) · 22 min"); the elevation and stress are under Details (the UI
 * review, 2026-10-28). In Go, Done leaves Go empty for the next trip; in Plan the plan stays to adjust. Keep riding (Undo
 * before) starts the same ride again, as it did before.
 *
 * Not timed: it stays until Done or Undo (WCAG 2.2.1); no Escape, as Done in Go empties the plan. The focus goes to Done; "Ride ended." is said by the
 * page's polite region (App), as a region mounted with its text in it is often not read (review F6).
 */
import { useEffect, useId, useRef, useState } from "react";
import { stressBarKey, stressBarLabel } from "./lib/quickFigures.ts";
import { segmentClass, segmentStyle, stressSegments } from "./lib/stressBar.ts";
import { elevationSpan, summaryRows, type RideStats } from "./lib/rideStats.ts";
import { METRES_PER_MILE, formatClimb, formatDistance, formatDuration } from "./lib/format.ts";
import { t } from "./lib/i18n.ts";
import { SAVE_SPOT_TEXT, SAVED_TO_FAVORITES } from "./lib/favoritePlaces.ts";
import { SAVE_ROUTE } from "./lib/savedRoutes.ts";
import { OPEN_REPORTS, REPORTS_WHERE, openCount, outstandingSaid, useReport311Log } from "./lib/report311Log.ts";
import { DO_ANOTHER_TRIP, FINISH_SESSION, REBALANCE_TODAY, dayRows, type RebalanceDay } from "./lib/rebalanceDay.ts";
import { rideCueLog } from "./lib/cueRecorder.ts";
import { copyText, selectionCopy } from "./lib/sidebar.ts";
import { closedSpots, feltStretches } from "./lib/rideFeedback.ts";
import { ClosedOffer, FeltDifferent } from "./RideFeedback.tsx";

export const RIDE_SUMMARY_TITLE = t("Ride ended");
/** The ride's cue log, offered only after a ride where a cue went wrong (lib/cueRecorder.ts; the owner, 2026-11-12). */
export const COPY_CUE_LOG = t("Copy cue log");
export const CUE_LOG_COPIED = t("Cue log copied.");
export const CUE_LOG_NOT_COPIED = t("Could not copy the cue log.");
/** The stress shares are shown once this much was ridden along the route. */
const STRESS_MIN_M = METRES_PER_MILE / 10;

/** Whether the ride's heights are worth a chart: some heights, along a tenth of a mile or more. */
function elevationDrawn(stats: RideStats): boolean {
  const points = stats.elevation;
  return !!elevationSpan(stats) && points.length > 0 && points[points.length - 1].atM - points[0].atM >= STRESS_MIN_M;
}

/** The summary's first line: where, how far, how long ("Union Station · 2.6 mi (4.2 km) · 22 min"). */
export function summaryLead(stats: RideStats, endedAt: number, destination: string | null | undefined): string[] {
  const movingS = stats.movingMs / 1000;
  const time = movingS >= 30 ? movingS : Math.max(0, (endedAt - stats.startedAt) / 1000);
  return [destination ?? "", formatDistance(stats.distanceM), formatDuration(time)].filter(Boolean);
}

/** The ride's heights as a filled line (the owner, 2026-10-20: "Show elevation too!"), its lowest and highest in words. */
function ElevationFigure({ stats }: { stats: RideStats }) {
  const span = elevationSpan(stats);
  if (!span || !elevationDrawn(stats)) return null;
  const points = stats.elevation;
  const from = points[0].atM;
  const length = points[points.length - 1].atM - from;
  // At least 30 ft (about 9 m) of height in the box, so a flat ride is drawn flat, not as noise.
  const rise = Math.max(span.hi - span.lo, 9);
  const W = 300;
  const H = 60;
  const x = (atM: number) => ((atM - from) / length) * W;
  const y = (m: number) => H - 2 - ((m - span.lo) / rise) * (H - 4);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(p.atM).toFixed(1)},${y(p.m).toFixed(1)}`).join("");
  const lowest = t("Lowest {height}", { height: formatClimb(span.lo) });
  const highest = t("Highest {height}", { height: formatClimb(span.hi) });
  return (
    <figure className="ride-summary-elevation">
      <figcaption>{t("Elevation")}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={t("Elevation along the ride. {lowest}. {highest}.", { lowest, highest })}>
        <path d={`${line}L${W},${H}L0,${H}Z`} className="ride-summary-elevation-area" />
        <path d={line} className="ride-summary-elevation-line" vectorEffect="non-scaling-stroke" />
      </svg>
      {/* Each capitalised (the owner, 2026-10-20: "the H in highest should be capitalized"), side by side where they fit. */}
      <p aria-hidden="true">
        <span>{lowest}</span> <span>{highest}</span>
      </p>
    </figure>
  );
}


export function RideSummaryCard({
  stats,
  endedAt,
  note,
  favorite = null,
  draft = null,
  destination = null,
  onDone,
  onUndo,
  onReports,
  rebalance = null,
  origin = null,
}: {
  stats: RideStats;
  endedAt: number;
  /** A line under the title where the plan changed (Plan: "The route now starts where you are."). */
  note?: string | null;
  /**
   * Signed in, the ride's destination, to save to Favorites (lib/favoritePlaces.ts; Stephen 2026-10-26); null for a
   * loop, Home, or signed out. Once saved, the button gives way to a line that says so.
   */
  favorite?: { name: string; saved: boolean; onSave: () => void } | null;
  /**
   * Signed in, a ride on an assistant's draft (lib/drafts.ts; the owner, 2026-11-09: "a button ... at the end of the
   * ride to save the ride, otherwise it's temporary"): its name, `left` ("Draft, 5 days left"), and Save route until
   * `said` says it was saved (or why not, with the button kept).
   */
  draft?: { name: string; left: string; saving: boolean; saved: boolean; said: string | null; onSave: () => void } | null;
  /** The ride's destination's name, where the map has one, for the first line; none for a loop. */
  destination?: string | null;
  onDone: () => void;
  onUndo: () => void;
  /** Closes the summary, as Done does, and opens Reports at the 311 checklist. */
  onReports: () => void;
  /**
   * A Rebalance Ride (lib/rebalanceDay.ts; Stephen, 2026-11-07): the day's totals, this ride counted, and Do another
   * trip first, which plans the next one from here; Done is Finish session.
   */
  rebalance?: { day: RebalanceDay; onAnother: () => void } | null;
  /**
   * The API's origin, for the two lines that learn from the ride (lib/rideFeedback.ts): "Anything feel different from
   * its rating?" and, after Road closed presses, the offer to send them for review. None: neither line shows.
   */
  origin?: string | null;
}) {
  const done = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  // The ride's cue log, as it was when the ride ended; "" when every cue went as planned (then no link at all).
  const [cueLog] = useState(() => (rideCueLog.wentWrong() ? rideCueLog.text() : ""));
  const [cueLogSaid, setCueLogSaid] = useState("");
  const copyCueLog = async () => {
    const copied = await copyText(cueLog, navigator.clipboard, selectionCopy);
    setCueLogSaid(copied ? CUE_LOG_COPIED : CUE_LOG_NOT_COPIED);
  };
  useEffect(() => {
    done.current?.focus();
  }, []);
  // Saved: the Save route button the focus was on gives way to a line, so the focus goes to Done, not the page.
  const draftSaved = draft?.saved ?? false;
  useEffect(() => {
    if (draftSaved && (document.activeElement === null || document.activeElement === document.body)) done.current?.focus();
  }, [draftSaved]);
  // A tab stop only while it scrolls (the v0.10.1 end review): otherwise one more stop that does nothing. Measured
  // again as the screen or the text size changes.
  const body = useRef<HTMLDivElement>(null);
  const [scrolls, setScrolls] = useState(false);
  // Problems logged for 311 and not yet reported, on any ride: where to find them, and a way there.
  const toReport = openCount(useReport311Log());
  const owes = toReport > 0;
  useEffect(() => {
    const element = body.current;
    if (!element) return;
    const measure = () => setScrolls(element.scrollHeight > element.clientHeight);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    for (const child of Array.from(element.children)) observer.observe(child);
    return () => observer.disconnect();
    // Again when the 311 line comes or goes (an account's log can arrive after the summary is up).
  }, [owes]);
  const rows = summaryRows(stats, endedAt);
  const ridden = Object.values(stats.stressM).reduce((sum, m) => sum + (m ?? 0), 0);
  const segments = ridden >= STRESS_MIN_M ? stressSegments(stats.stressM) : [];
  const felt = origin != null ? feltStretches(stats) : [];
  const spots = origin != null ? closedSpots(stats) : [];
  return (
    <section className="ride-summary" aria-labelledby={titleId}>
      <h2 id={titleId}>{RIDE_SUMMARY_TITLE}</h2>
      {/* The figures, chart and stress fill the screen between the title and the buttons (the owner, 2026-10-20: "The end
          ride panel should be scaled to fill the page, not go over"); where it cannot fit, this part scrolls, and can be
          reached by keyboard to scroll it, named by the title then (a tab stop needs a name). */}
      <div
        ref={body}
        className="ride-summary-body"
        role={scrolls ? "group" : undefined}
        aria-labelledby={scrolls ? titleId : undefined}
        tabIndex={scrolls ? 0 : undefined}
      >
        {/* Each figure kept whole on its line, never split between its number and its unit. */}
        <p className="ride-summary-lead">
          {summaryLead(stats, endedAt, destination).map((part, i) => (
            <span key={part}>
              {i > 0 && " "}
              <span>{i > 0 ? `· ${part}` : part}</span>
            </span>
          ))}
        </p>
        {note && <p className="hint">{note}</p>}
        {draft && (
          <div className="ride-summary-favorite ride-summary-draft">
            <p>
              {draft.said ?? draft.name} {!draft.saved && <span className="hint">{draft.left}</span>}
            </p>
            {!draft.saved && (
              <button type="button" className="secondary" aria-disabled={draft.saving || undefined} onClick={draft.saving ? undefined : draft.onSave}>
                {SAVE_ROUTE}
              </button>
            )}
          </div>
        )}
        {favorite && (
          <div className="ride-summary-favorite">
            <p>{favorite.saved ? SAVED_TO_FAVORITES(favorite.name) : favorite.name}</p>
            {!favorite.saved && (
              <button type="button" className="secondary" onClick={favorite.onSave}>
                {SAVE_SPOT_TEXT}
              </button>
            )}
          </div>
        )}
        {owes && (
          <div className="ride-summary-311">
            <p>
              {outstandingSaid(toReport)} <span className="hint">{REPORTS_WHERE}</span>
            </p>
            <button type="button" className="secondary" onClick={onReports}>
              {OPEN_REPORTS}
            </button>
          </div>
        )}
        <dl className="ride-summary-figures">
          {rows.map((row) => (
            <div key={row.name}>
              <dt>{row.name}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
        {rebalance && (
          <section className="ride-summary-day" aria-labelledby={`${titleId}-day`}>
            <h3 id={`${titleId}-day`}>{REBALANCE_TODAY}</h3>
            <dl className="ride-summary-figures">
              {dayRows(rebalance.day).map((row) => (
                <div key={row.name}>
                  <dt>{row.name}</dt>
                  <dd>{row.value}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}
        {/* Learning from the ride (lib/rideFeedback.ts): under the figures, each one line until pressed. */}
        {origin != null && spots.length > 0 && <ClosedOffer origin={origin} spots={spots} />}
        {origin != null && felt.length > 0 && <FeltDifferent origin={origin} stretches={felt} />}
        {/* The chart and the stress behind Details (the UI review, 2026-10-28), the figures in view. */}
        {(segments.length > 0 || elevationDrawn(stats)) && (
          <details className="ride-summary-details">
            <summary>{t("Details")}</summary>
            <ElevationFigure stats={stats} />
            {segments.length > 0 && (
              <figure className="stress ride-summary-stress">
                <figcaption>
                  {t("Traffic stress")}
                  <span className="visually-hidden">{t(", along the route")}</span>
                </figcaption>
                <div className="stress-bar" role="img" aria-label={stressBarLabel(segments)}>
                  {segments
                    .filter((s) => s.fraction > 0)
                    .map((s) => (
                      <span
                        key={s.key}
                        className={`stress-seg ${segmentClass(s)}`}
                        style={{ width: `${s.fraction * 100}%`, ...segmentStyle(s) }}
                      />
                    ))}
                </div>
                <p className="stress-key" aria-hidden="true">
                  {stressBarKey(segments)}
                </p>
              </figure>
            )}
          </details>
        )}
      </div>
      <div className="ride-summary-actions">
        {rebalance ? (
          <>
            <button ref={done} type="button" onClick={rebalance.onAnother}>
              {DO_ANOTHER_TRIP}
            </button>
            <button type="button" className="secondary" onClick={onDone}>
              {FINISH_SESSION}
            </button>
          </>
        ) : (
          <button ref={done} type="button" onClick={onDone}>
            {t("Done")}
          </button>
        )}
        {/* Undo, as a text link (the UI review, 2026-10-28): the same ride again, from its figures so far. */}
        <button type="button" className="link ride-summary-keep" onClick={onUndo}>
          {t("Keep riding")}
        </button>
        {/* After a ride where a cue was dropped, cut off or stuck: its log to paste into a bug report, no places in it. */}
        {/* Its words become the answer, as Save route's do; the page's own region says things, never this card's (F6). */}
        {cueLog && (
          <button type="button" className="link ride-summary-keep" onClick={() => void copyCueLog()}>
            {cueLogSaid || COPY_CUE_LOG}
          </button>
        )}
      </div>
    </section>
  );
}
