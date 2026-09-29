/**
 * The route summary's facility breakdown and, when the hills slider sought
 * climbs, what that search found. A component of its own so App.tsx only
 * places it (another lane is changing App.tsx).
 */
import { formatClimb, formatDistance } from "./lib/format.ts";
import { avoidMetres, facilityRows } from "./lib/facilityBar.ts";
import type { RouteResponse } from "./lib/api.ts";
import { routeWarning } from "./lib/dialsPanel.ts";
import { ROUTE_BLUE, ROUTE_CASING_WIDTH, ROUTE_LINE_WIDTH, milesFirst, routeLegend } from "./lib/routeColours.ts";

export function FacilityBreakdown({ route }: { route: RouteResponse }) {
  const rows = facilityRows(route.facility_m);
  const seek = route.hills_seek;
  const avoid = avoidMetres(route.stress_m);
  const warning = routeWarning(route.preset, route.dials);
  const colours = routeLegend(route.stress_spans);
  return (
    <>
      {colours.length > 0 && (
        <figure className="stress route-colours">
          <figcaption>The route on the map, by traffic stress</figcaption>
          <ul className="stress-list" aria-label="Route colour legend">
            {colours.map((row) => (
              <li key={row.key}>
                <svg width="36" height="12" aria-hidden="true">
                  <line x1="3" y1="6" x2="33" y2="6" stroke={ROUTE_BLUE} strokeWidth={ROUTE_CASING_WIDTH} strokeLinecap="round" />
                  <line x1="3" y1="6" x2="33" y2="6" stroke={row.color} strokeWidth={ROUTE_LINE_WIDTH} strokeLinecap="round" />
                </svg>
                <span className="stress-name">{row.short}</span>
                <span className="stress-label">{row.label}</span>
                <span className="stress-pct">{milesFirst(row.metres)}</span>
              </li>
            ))}
          </ul>
        </figure>
      )}
      {warning && (
        <p className="notice traffic-tolerant" role="note">
          {warning}
        </p>
      )}
      {avoid > 0 && (
        <p className="notice avoid" role="note">
          {formatDistance(avoid)} of this route is on roads marked legal but best avoided, such as expressways and some bridge roadways. The
          planner uses them only where every other way is much longer.
        </p>
      )}
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
              ? "Looking for climbs is done only when the start and end are within 50 km of each other; this is the fastest route."
              : seek.limited === "timed_out"
                ? "Looking for climbs took too long this time; this is the fastest route."
              : seek.chosen === 0
                ? `None of the ${seek.candidates - 1} alternatives climbed more within the distance allowed; this is the fastest route.`
                : `Chose a route with ${formatClimb(seek.extra_climb_m)} more climbing for ${formatDistance(seek.extra_distance_m)} more distance, from ${seek.candidates} routes compared.`}
        </p>
      )}
    </>
  );
}
