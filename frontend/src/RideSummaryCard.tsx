/**
 * After End ride (the owner, 2026-10-20: "When ending a ride, perhaps summary stats rather than programming that ride
 * again"): the ride's own figures (lib/rideStats.ts) in one card, with Done and Undo. In Go, Done leaves Go empty for
 * the next trip; in Plan the plan stays to adjust. Undo starts the same ride again, as it did before.
 *
 * Not timed: it stays until Done, Undo or Escape (WCAG 2.2.1). The focus goes to Done; the summary is said by the
 * page's polite region (App), as a region mounted with its text in it is often not read (review F6).
 */
import { useEffect, useId, useRef } from "react";
import { stressBarKey, stressBarLabel } from "./lib/quickFigures.ts";
import { stressSegments } from "./lib/stressBar.ts";
import { summaryRows, type RideStats } from "./lib/rideStats.ts";
import { METRES_PER_MILE } from "./lib/format.ts";

export const RIDE_SUMMARY_TITLE = "Ride ended";
/** The stress shares are shown once this much was ridden along the route. */
const STRESS_MIN_M = METRES_PER_MILE / 10;

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
    <section
      className="ride-summary"
      aria-labelledby={titleId}
      onKeyDown={(event) => {
        if (event.key === "Escape") onDone();
      }}
    >
      <h2 id={titleId}>{RIDE_SUMMARY_TITLE}</h2>
      {note && <p className="hint">{note}</p>}
      <dl className="ride-summary-figures">
        {rows.map((row) => (
          <div key={row.name}>
            <dt>{row.name}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
      {segments.length > 0 && (
        <figure className="stress ride-summary-stress">
          <figcaption>Traffic stress, along the route</figcaption>
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
