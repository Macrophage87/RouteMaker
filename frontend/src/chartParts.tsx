/**
 * What the route chart (ElevationChart.tsx) and a Mass Ride's three charts (MassRideCharts.tsx) share:
 * the viewBox's width and plot edges, so every chart is drawn on the same distance axis; the patterns
 * that keep colour from being the only cue; the junction marker shapes; the elevation axis's figures;
 * and the tables behind "... as tables", the pictures' text alternative.
 */
import type { ReactNode } from "react";
import type { RouteProfile, RouteResponse } from "./lib/api.ts";
import { SEVERITY_COLOURS } from "./lib/intersectionMarkers.ts";
import {
  AVOID_FRAME,
  FLOW_BANDS,
  PARTIAL_JUNCTIONS,
  bottleneckRows,
  calmRows,
  climbRows,
  crossingCaption,
  crossingRows,
  crossingsPartial,
  elevationWords,
  usableCalm,
  type ChartKind,
  type CorkerLoad,
} from "./lib/profileChart.ts";

export const WIDTH = 360;
export const LEFT = 46;
export const RIGHT = WIDTH - 8;

/** The patterns' ink: translucent so it shows on every band colour. */
export const INK = "rgba(255,255,255,0.55)";
export const DARK_INK = "rgba(20,24,32,0.55)";

/** The grade bands' patterns over the amber: `${uid}-dots` (5% to 8%) and `${uid}-hatch` (8% or more). */
export function GradePatterns({ uid }: { uid: string }): ReactNode {
  return (
    <>
      {/* 5% to 8%: sparse dark dots over the amber (the a11y review's S2: the amber alone is 1.3:1 on the light theme's grey). */}
      <pattern id={`${uid}-dots`} width="4" height="4" patternUnits="userSpaceOnUse">
        <circle cx="2" cy="2" r="0.8" fill="#1b1e24" fillOpacity="0.75" />
      </pattern>
      {/* 8% or more: dark diagonal lines over the amber. */}
      <pattern id={`${uid}-hatch`} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <line x1="0" y1="0" x2="0" y2="5" stroke="#1b1e24" strokeWidth="2" />
      </pattern>
    </>
  );
}

/** The riders bands' patterns, `${uid}-flow-<pattern>` (332). */
export function FlowPatterns({ uid }: { uid: string }): ReactNode {
  return (
    <>
      {FLOW_BANDS.map((band) => (
        <pattern key={band.index} id={`${uid}-flow-${band.pattern}`} width="6" height="6" patternUnits="userSpaceOnUse">
          {band.pattern === "crosshatch" && <path d="M0 0L6 6M6 0L0 6" stroke={INK} strokeWidth="1.2" />}
          {band.pattern === "diagonal" && <path d="M-1 5L5 -1M2 8L8 2" stroke={DARK_INK} strokeWidth="1.4" />}
          {band.pattern === "dots" && <circle cx="3" cy="3" r="1.1" fill={INK} />}
          {band.pattern === "horizontal" && <path d="M0 1.5H6M0 4.5H6" stroke={INK} strokeWidth="1" />}
        </pattern>
      ))}
    </>
  );
}

/** Avoid's texture (397): dark chevrons on magenta, its own, not the bottleneck's cross-hatch. */
export function AvoidPattern({ uid }: { uid: string }): ReactNode {
  return (
    <pattern id={`${uid}-avoid`} width="8" height="6" patternUnits="userSpaceOnUse">
      <path d="M0 5L4 1L8 5" stroke={AVOID_FRAME} strokeOpacity="0.7" strokeWidth="1.3" fill="none" />
    </pattern>
  );
}

export function feet(m: number): string {
  return elevationWords(m).split(" (")[0];
}

export function metres(m: number): string {
  const text = elevationWords(m);
  return `(${text.split(" (")[1] ?? ""}`;
}

export function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** A junction's marker: the planner's triangle (higher stress) or diamond (very high), or a dot where it is major only for its busy road. */
export function CrossingMarker({ severity, x, y }: { severity: "orange" | "red" | null; x: number; y: number }): ReactNode {
  if (severity === "orange") {
    const c = SEVERITY_COLOURS.orange;
    return <path d={`M${x} ${y - 6} L${x + 6} ${y + 5} L${x - 6} ${y + 5} Z`} fill={c.fill} stroke={c.stroke} strokeWidth="1" strokeLinejoin="round" />;
  }
  if (severity === "red") {
    const c = SEVERITY_COLOURS.red;
    return <path d={`M${x} ${y - 7} L${x + 7} ${y} L${x} ${y + 7} L${x - 7} ${y} Z`} fill={c.fill} stroke={c.stroke} strokeWidth="1" strokeLinejoin="round" />;
  }
  return <circle className="pc-dot" cx={x} cy={y} r="3.5" />;
}

/** The junction shapes' key entries: the triangle, the diamond and the dot, each with its words. */
export function JunctionKey({ orange = true, red = true, dot = true }: { orange?: boolean; red?: boolean; dot?: boolean }): ReactNode {
  return (
    <>
      {orange && (
        <li>
          <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 2.5 22.5 20.5H1.5Z" fill={SEVERITY_COLOURS.orange.fill} stroke={SEVERITY_COLOURS.orange.stroke} strokeWidth="2" />
          </svg>
          Higher stress junction (triangle)
        </li>
      )}
      {red && (
        <li>
          <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 1.5 22.5 12 12 22.5 1.5 12Z" fill={SEVERITY_COLOURS.red.fill} stroke={SEVERITY_COLOURS.red.stroke} strokeWidth="2" />
          </svg>
          Very high stress junction (diamond)
        </li>
      )}
      {dot && (
        <li>
          <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="6" className="pc-dot" />
          </svg>
          Busy road crossed or joined (dot)
        </li>
      )}
    </>
  );
}

/**
 * The climbs, and on a Mass Ride the bottlenecks and the intersections (with the corker load at
 * each), as tables: the pictures' text alternative.
 */
export function Tables({
  profile,
  kind,
  spans,
  total,
  load = null,
}: {
  profile: RouteProfile;
  kind: ChartKind;
  spans: RouteResponse["stress_spans"];
  total: number;
  load?: CorkerLoad | null;
}) {
  const rows = climbRows(profile, kind, spans);
  const calm = kind === "stress" ? usableCalm(profile) : null;
  const calmTable = calm ? calmRows(profile, calm, total) : [];
  const bottlenecks = kind === "mass" ? bottleneckRows(profile) : [];
  const crossings = kind === "mass" ? crossingRows(profile, load) : [];
  const checked = profile.crossings !== null && profile.crossings !== undefined;
  return (
    <div className="pc-tables">
      {rows.length === 0 ? (
        <p className="hint">No sustained climbs on this route.</p>
      ) : (
        <div className="pc-table-wrap">
          <table className="pc-table">
            <caption>Climbs, in the order ridden</caption>
            <thead>
              <tr>
                <th scope="col">Start</th>
                <th scope="col">Length</th>
                <th scope="col">Gain</th>
                <th scope="col">Average grade</th>
                <th scope="col">Maximum grade</th>
                <th scope="col">Stress</th>
                {kind === "mass" && <th scope="col">Capacity drop</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  <th scope="row">{row.start}</th>
                  <td>{row.length}</td>
                  <td>{row.gain}</td>
                  <td>{row.average}</td>
                  <td>{row.maximum}</td>
                  <td>{row.stress}</td>
                  {kind === "mass" && <td>{row.capacity}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {calm && (
        <div className="pc-table-wrap">
          <table className="pc-table">
            <caption>Rolling stress, calm miles per mile over the mile around each point</caption>
            <thead>
              <tr>
                <th scope="col">At</th>
                <th scope="col">Calm miles per mile</th>
                <th scope="col">Reads as</th>
                <th scope="col">Junctions to watch since the row before</th>
              </tr>
            </thead>
            <tbody>
              {calmTable.map((row, i) => (
                <tr key={i}>
                  <th scope="row">{row.at}</th>
                  <td>{row.value}</td>
                  <td>{row.reads}</td>
                  <td>{row.junctions}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {kind === "mass" &&
        (bottlenecks.length === 0 ? (
          <p className="hint">No bottlenecks (under 60 riders per minute) where the width is known.</p>
        ) : (
          <div className="pc-table-wrap">
            <table className="pc-table">
              <caption>Bottlenecks, under 60 riders per minute, in the order ridden</caption>
              <thead>
                <tr>
                  <th scope="col">Start</th>
                  <th scope="col">Length</th>
                  <th scope="col">Lowest riders per minute</th>
                </tr>
              </thead>
              <tbody>
                {bottlenecks.map((row, i) => (
                  <tr key={i}>
                    <th scope="row">{row.start}</th>
                    <td>{row.length}</td>
                    <td>{row.lowest}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      {kind === "mass" &&
        (!checked ? (
          <p className="hint">Major intersections were not checked for this route.</p>
        ) : crossings.length === 0 ? (
          <p className="hint">
            {crossingsPartial(profile)
              ? `No ${PARTIAL_JUNCTIONS}s on this route; the other busy-road intersections were not checked, so there may be some.`
              : "No major intersections on this route."}
          </p>
        ) : (
          <div className="pc-table-wrap">
            <table className="pc-table">
              <caption>{crossingCaption(profile)}</caption>
              <thead>
                <tr>
                  <th scope="col">At</th>
                  <th scope="col">Street</th>
                  <th scope="col">Marker</th>
                  <th scope="col">Corkers</th>
                  {load && <th scope="col">Corker load around it</th>}
                </tr>
              </thead>
              <tbody>
                {crossings.map((row, i) => (
                  <tr key={i}>
                    <th scope="row">{row.mile}</th>
                    <td>{row.street}</td>
                    <td>{row.marker}</td>
                    <td>{row.corkers}</td>
                    {load && <td>{row.load}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </div>
  );
}
