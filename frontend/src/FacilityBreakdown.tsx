/**
 * The route summary's facility breakdown and, when the hills slider sought
 * climbs, what that search found. A component of its own so App.tsx only
 * places it (another lane is changing App.tsx).
 */
import { useId } from "react";
import { formatDistance } from "./lib/format.ts";
import { avoidMetres, breakdownParts, facilityRows, type BreakdownPart } from "./lib/facilityBar.ts";
import type { RouteResponse } from "./lib/api.ts";
import { routeWarning } from "./lib/dialsPanel.ts";
import { useHighStressLanes, useStressStyle } from "./useStressStyle.ts";
import { ROUTE_CASING_WIDTH, routeCasing, routeLegend, routeMarkDash, routeMarkWidth } from "./lib/routeColours.ts";
import { seekNote } from "./lib/summary.ts";

/**
 * A row of a figure's list, read as label, figure, hint with a pause between
 * (the a11y review's N5: "Traffic-free pathOff-road paths...19%"). The grid puts
 * the hint back before the figure on screen (styles.css, .stress-list).
 */
const PAUSE = <span className="visually-hidden">, </span>;

/**
 * `part` splits it for the sidebar's layout (OWNER-DECISIONS 312): the notices (the traffic-tolerant
 * warning, the roads best avoided, what the hills search found) stay in view, and the figures (the route
 * colors and the bike facilities) sit in the "Stress and facilities" fold. The default is all of it.
 */
export function FacilityBreakdown({ route, part = "all" }: { route: RouteResponse; part?: BreakdownPart }) {
  const { figures, notices } = breakdownParts(part);
  const id = useId();
  useStressStyle(); // the route colours below follow the accessibility switch
  const showHighLanes = useHighStressLanes(); // painted lanes on LTS 4 and Avoid count as no facility unless the switch is on
  const rows = facilityRows(route.facility_m, route.stress_spans, showHighLanes);
  const seek = seekNote(route.hills_seek);
  const avoid = avoidMetres(route.stress_m);
  const warning = routeWarning(route.preset, route.dials);
  const colours = routeLegend(route.stress_spans);
  const casing = routeCasing();
  return (
    <>
      {figures && colours.length > 0 && (
        <figure className="stress route-colours" aria-labelledby={`${id}-colours`}>
          <figcaption id={`${id}-colours`}>The route on the map, by traffic stress</figcaption>
          <ul className="stress-list" aria-label="Route color legend">
            {colours.map((row) => (
              <li key={row.key}>
                <svg width="36" height="14" aria-hidden="true">
                  <line x1="3" y1="7" x2="33" y2="7" stroke={casing} strokeWidth={ROUTE_CASING_WIDTH} strokeLinecap="round" />
                  {row.ring && <line x1="3" y1="7" x2="33" y2="7" stroke={row.ring} strokeWidth={row.ringWidth} strokeLinecap="round" />}
                  <line x1="3" y1="7" x2="33" y2="7" stroke={row.halo} strokeWidth={row.haloWidth} strokeLinecap="round" />
                  <line x1="3" y1="7" x2="33" y2="7" stroke={row.color} strokeWidth={row.width} strokeLinecap="round" />
                  {/* Avoid's white dash-dot, as the map draws it (397: not the colour alone). */}
                  {row.mark && (
                    <line
                      className="route-avoid-mark"
                      x1="3"
                      y1="7"
                      x2="33"
                      y2="7"
                      stroke={row.mark}
                      strokeWidth={routeMarkWidth(row.width)}
                      strokeDasharray={routeMarkDash(row.width)}
                    />
                  )}
                </svg>
                <span className="stress-name">{row.short}</span>
                {PAUSE}
                <span className="stress-pct">{formatDistance(row.metres)}</span>
                {PAUSE}
                <span className="stress-label">{row.label}</span>
              </li>
            ))}
          </ul>
        </figure>
      )}
      {notices && warning && (
        <p className="notice traffic-tolerant" role="note">
          {warning}
        </p>
      )}
      {notices && avoid > 0 && (
        <p className="notice avoid" role="note">
          {formatDistance(avoid)} of this route is on roads marked legal but best avoided, such as expressways and some bridge roadways. The
          planner uses them only where every other way is much longer.
        </p>
      )}
      {figures && rows.length > 0 && (
        <figure className="stress facility" aria-labelledby={`${id}-facility`}>
          <figcaption id={`${id}-facility`}>Bike facilities along the route</figcaption>
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
                {PAUSE}
                <span className="stress-pct">{r.percent}%</span>
                {PAUSE}
                <span className="stress-label">{r.hint}</span>
              </li>
            ))}
          </ul>
        </figure>
      )}
      {notices && seek && (
        <p className="hint seek" role="note">
          {seek}
        </p>
      )}
    </>
  );
}
