/**
 * After End ride (the owner, 2026-10-20: "When ending a ride, perhaps summary stats rather than programming that ride
 * again"): the ride's own figures (lib/rideStats.ts) in one card, with Done and Undo. In Go, Done leaves Go empty for
 * the next trip; in Plan the plan stays to adjust. Undo starts the same ride again, as it did before.
 *
 * Not timed: it stays until Done or Undo (WCAG 2.2.1); no Escape, as Done in Go empties the plan. The focus goes to Done; "Ride ended." is said by the
 * page's polite region (App), as a region mounted with its text in it is often not read (review F6).
 */
import { useEffect, useId, useRef } from "react";
import { stressBarKey, stressBarLabel } from "./lib/quickFigures.ts";
import { stressSegments } from "./lib/stressBar.ts";
import { elevationSpan, summaryRows, type RideStats } from "./lib/rideStats.ts";
import { METRES_PER_MILE, formatClimb } from "./lib/format.ts";

export const RIDE_SUMMARY_TITLE = "Ride ended";
/** The stress shares are shown once this much was ridden along the route. */
const STRESS_MIN_M = METRES_PER_MILE / 10;

/** The ride's heights as a filled line (the owner, 2026-10-20: "Show elevation too!"), its lowest and highest in words. */
function ElevationFigure({ stats }: { stats: RideStats }) {
  const span = elevationSpan(stats);
  if (!span) return null;
  const points = stats.elevation;
  const from = points[0].atM;
  const length = points[points.length - 1].atM - from;
  if (!(length >= STRESS_MIN_M)) return null;
  // At least 30 ft (about 9 m) of height in the box, so a flat ride is drawn flat, not as noise.
  const rise = Math.max(span.hi - span.lo, 9);
  const W = 300;
  const H = 60;
  const x = (atM: number) => ((atM - from) / length) * W;
  const y = (m: number) => H - 2 - ((m - span.lo) / rise) * (H - 4);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(p.atM).toFixed(1)},${y(p.m).toFixed(1)}`).join("");
  const lowest = `Lowest ${formatClimb(span.lo)}`;
  const highest = `Highest ${formatClimb(span.hi)}`;
  return (
    <figure className="ride-summary-elevation">
      <figcaption>Elevation</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`Elevation along the ride. ${lowest}. ${highest}.`}>
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
  onDone,
  onUndo,
}: {
  stats: RideStats;
  endedAt: number;
  /** A line under the title where the plan changed (Plan: "The route now starts where you are."). */
  note?: string | null;
  onDone: () => void;
  onUndo: () => void;
}) {
  const done = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  useEffect(() => {
    done.current?.focus();
  }, []);
  const rows = summaryRows(stats, endedAt);
  const ridden = Object.values(stats.stressM).reduce((sum, m) => sum + (m ?? 0), 0);
  const segments = ridden >= STRESS_MIN_M ? stressSegments(stats.stressM) : [];
  return (
    <section className="ride-summary" aria-labelledby={titleId}>
      <h2 id={titleId}>{RIDE_SUMMARY_TITLE}</h2>
      {/* The figures, chart and stress fill the screen between the title and the buttons (the owner, 2026-10-20: "The end
          ride panel should be scaled to fill the page, not go over"); only very large system text scrolls, here. */}
      <div className="ride-summary-body">
        {note && <p className="hint">{note}</p>}
        <dl className="ride-summary-figures">
          {rows.map((row) => (
            <div key={row.name}>
              <dt>{row.name}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
        <ElevationFigure stats={stats} />
        {segments.length > 0 && (
          <figure className="stress ride-summary-stress">
            <figcaption>Traffic stress</figcaption>
            <div className="stress-bar" role="img" aria-label={stressBarLabel(segments)}>
              {segments
                .filter((s) => s.fraction > 0)
                .map((s) => (
                  <span
                    key={s.key}
                    className={`stress-seg stress-seg-${s.key}`}
                    style={{ width: `${s.fraction * 100}%`, backgroundColor: s.color, ["--seg-accent" as string]: s.casing }}
                  />
                ))}
            </div>
            <p className="stress-key" aria-hidden="true">
              {stressBarKey(segments)}
            </p>
          </figure>
        )}
      </div>
      <div className="ride-summary-actions">
        <button ref={done} type="button" onClick={onDone}>
          Done
        </button>
        <button type="button" className="secondary" onClick={onUndo}>
          Undo
        </button>
      </div>
    </section>
  );
}
