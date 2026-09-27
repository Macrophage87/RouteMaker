/**
 * The route summary's facility breakdown and, when the hills slider sought
 * climbs, what that search found. A component of its own so App.tsx only
 * places it (another lane is changing App.tsx).
 */
import { formatClimb, formatDistance } from "./lib/format.ts";
import { facilityRows } from "./lib/facilityBar.ts";
import type { RouteResponse } from "./lib/api.ts";

export function FacilityBreakdown({ route }: { route: RouteResponse }) {
  const rows = facilityRows(route.facility_m);
  const seek = route.hills_seek;
  return (
    <>
      {rows.length > 0 && (
        <figure className="stress facility">
          <figcaption>Bike facilities along the route</figcaption>
          <div className="stress-bar" aria-hidden="true">
            {rows
              .filter((r) => r.fraction > 0)
              .map((r) => (
                <span
                  key={r.key}
                  className={`stress-seg facility-seg-${r.key}`}
                  style={{ width: `${r.fraction * 100}%`, backgroundColor: r.color }}
                  title={`${r.label}: ${r.percent}%`}
                />
              ))}
          </div>
          <ul className="stress-list">
            {rows.map((r) => (
              <li key={r.key}>
                <span className="swatch" style={{ backgroundColor: r.color }} aria-hidden="true" />
                <span className="stress-name">{r.label}</span>
                <span className="stress-label">{r.hint}</span>
                <span className="stress-pct">{r.percent}%</span>
              </li>
            ))}
          </ul>
        </figure>
      )}
      {seek && (
        <p className="hint seek" role="note">
          {seek.limited === "two_points"
            ? "Looking for climbs works on routes with just a start and an end; this one has via points, so it is the fastest route."
            : seek.limited === "long_ride"
              ? "Looking for climbs is not done on long rides; this is the fastest route."
              : seek.chosen === 0
                ? `None of the ${seek.candidates - 1} alternatives climbed more within the distance allowed; this is the fastest route.`
                : `Chose a route with ${formatClimb(seek.extra_climb_m)} more climbing for ${formatDistance(seek.extra_distance_m)} more distance, from ${seek.candidates} routes compared.`}
        </p>
      )}
    </>
  );
}
