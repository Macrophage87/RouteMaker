/**
 * The route summary's facility breakdown and, when the hills slider sought
 * climbs, what that search found. A component of its own so App.tsx only
 * places it (another lane is changing App.tsx).
 */
import { SEEK_MAX_SPAN_M, formatClimb, formatDistance, formatRoughDistance } from "./lib/format.ts";
import { avoidMetres, facilityRows } from "./lib/facilityBar.ts";
import type { RouteResponse } from "./lib/api.ts";
import { routeWarning } from "./lib/dialsPanel.ts";
import { useHighStressLanes, useStressStyle } from "./useStressStyle.ts";
import { ROUTE_CASING_WIDTH, routeCasing, routeLegend } from "./lib/routeColours.ts";

export function FacilityBreakdown({ route }: { route: RouteResponse }) {
  useStressStyle(); // the route colours below follow the accessibility switch
  const showHighLanes = useHighStressLanes(); // painted lanes on LTS 4 and Avoid count as no facility unless the switch is on
  const rows = facilityRows(route.facility_m, route.stress_spans, showHighLanes);
  const seek = route.hills_seek;
  const avoid = avoidMetres(route.stress_m);
  const warning = routeWarning(route.preset, route.dials);
  const colours = routeLegend(route.stress_spans);
  const casing = routeCasing();
  return (
    <>
      {colours.length > 0 && (
        <figure className="stress route-colours">
          <figcaption>The route on the map, by traffic stress</figcaption>
          <ul className="stress-list" aria-label="Route color legend">
            {colours.map((row) => (
              <li key={row.key}>
                <svg width="36" height="14" aria-hidden="true">
                  <line x1="3" y1="7" x2="33" y2="7" stroke={casing} strokeWidth={ROUTE_CASING_WIDTH} strokeLinecap="round" />
                  <line x1="3" y1="7" x2="33" y2="7" stroke={row.halo} strokeWidth={row.haloWidth} strokeLinecap="round" />
                  <line x1="3" y1="7" x2="33" y2="7" stroke={row.color} strokeWidth={row.width} strokeLinecap="round" />
                </svg>
                <span className="stress-name">{row.short}</span>
                <span className="stress-label">{row.label}</span>
                <span className="stress-pct">{formatDistance(row.metres)}</span>
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
                <span className={`swatch facility-seg-${r.key}`} style={{ backgroundColor: r.color }} aria-hidden="true" />
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
            ? "Looking for climbs works on routes with just a start and an end; this one has stops, so it is the fastest route."
            : seek.limited === "long_ride"
              ? `Looking for climbs is done only when the start and end are within ${formatRoughDistance(SEEK_MAX_SPAN_M)} of each other; this is the fastest route.`
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
