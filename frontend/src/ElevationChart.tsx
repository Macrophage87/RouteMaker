/**
 * The route's elevation chart (OWNER-DECISIONS 322, 323; mockup v3, Route "Elevation and stress"),
 * and the Mass Ride version of it (328, 329, 332, 333; mockup v3, Mass Ride). Drawn here in SVG
 * from the API's `profile`, with no chart library.
 *
 * - Every ride type but Mass Ride: distance across (miles, kilometres in brackets), elevation up
 *   (feet, metres in brackets), the 5-8% and 8%-or-more grades picked out in amber (solid, and
 *   hatched, so colour is not the only cue), and a rolling stress strip under it in the tier styles.
 * - Mass Ride: in place of the strip, a filled area of the grade-adjusted riders a minute in the
 *   spectral band colours (each also with a pattern), dotted guides at 60, 120 and 200, its own
 *   axis, and the major intersections as ticks, names and the junction markers.
 *
 * The scrub. Hovering or touching moves a marker on the map (`onScrub`), and so does the keyboard:
 * the plot is a slider, whose arrow keys step along the route and whose value text is the spoken
 * sentence ("Mile 4.2: elevation 310 ft (94 m), grade 6%, LTS 2"). A text alternative stands beside
 * the picture: a summary, and the climbs (and, on a Mass Ride, the intersections) as tables.
 * Everything it says is made in lib/profileChart.ts.
 */
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import type { RouteProfile, RouteResponse } from "./lib/api.ts";
import type { LonLat } from "./lib/geo.ts";
import { SEVERITY_COLOURS } from "./lib/intersectionMarkers.ts";
import {
  FLOW_BANDS,
  FLOW_GUIDES,
  GRADE_BANDS,
  GRADE_BAND_FILL,
  axisDistance,
  axisLength,
  chartKind,
  climbRows,
  crossingRows,
  elevationArea,
  elevationLine,
  elevationRange,
  elevationWords,
  flowLine,
  flowShapes,
  gradeBandShapes,
  linear,
  lonLatAt,
  placeCrossings,
  positionAfterKey,
  readingAt,
  ridersTop,
  stripSections,
  summaryText,
  type ChartKind,
  type Plot,
} from "./lib/profileChart.ts";
import { spanClass } from "./lib/routeColours.ts";

const WIDTH = 360;
const LEFT = 46;
const RIGHT = WIDTH - 8;

/** The vertical layout of each chart, in viewBox units. */
const LAYOUT = {
  stress: { height: 150, elevTop: 10, elevBottom: 98, stripTop: 108, stripBottom: 120, axisY: 138 },
  mass: { height: 208, elevTop: 12, elevBottom: 66, markerY: 79, flowTop: 94, flowBottom: 150, labelY: 162, axisY: 200 },
} as const;

/** The patterns' ink: translucent so it shows on every band colour. */
const INK = "rgba(255,255,255,0.55)";
const DARK_INK = "rgba(20,24,32,0.55)";

export function ElevationChart({
  route,
  profile,
  onScrub,
}: {
  route: RouteResponse;
  profile: RouteProfile;
  /** The map point under the scrub, or null when there is none (the chart lost it). */
  onScrub?: (point: LonLat | null) => void;
}) {
  const kind: ChartKind = chartKind(route);
  const uid = useId().replace(/[^A-Za-z0-9_-]/g, "");
  const total = axisLength(route, profile);
  const [at, setAt] = useState<number | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const active = hover ?? at;
  const reading = useMemo(() => readingAt(route, profile, active ?? at ?? 0, kind), [route, profile, active, at, kind]);
  const summary = useMemo(() => summaryText(route, profile, kind), [route, profile, kind]);
  const slider = useRef<HTMLDivElement | null>(null);
  const heard = useRef(onScrub);
  heard.current = onScrub;

  // The map marker follows the scrub; it goes when the chart does.
  useEffect(() => {
    if (!heard.current) return;
    heard.current(active === null ? null : lonLatAt(route.geometry.coordinates, reading.m, total));
  }, [active, reading.m, route, total]);
  useEffect(() => () => heard.current?.(null), []);

  const layout = LAYOUT[kind];
  const range = useMemo(() => elevationRange(profile), [profile]);
  const elevTop = layout.elevTop;
  const elevBottom = layout.elevBottom;
  const x = useMemo(() => linear(0, total, LEFT, RIGHT), [total]);
  const plot: Plot = useMemo(
    () => ({ x, y: linear(range.lo, range.hi, elevBottom, elevTop), left: LEFT, right: RIGHT, top: elevTop, bottom: elevBottom }),
    [x, range, elevTop, elevBottom],
  );
  const mass = kind === "mass" ? LAYOUT.mass : null;
  const top = useMemo(() => ridersTop(profile), [profile]);
  const flowY = useMemo(() => (mass ? linear(0, top, mass.flowBottom, mass.flowTop) : null), [mass, top]);

  const area = useMemo(() => elevationArea(profile, plot), [profile, plot]);
  const line = useMemo(() => elevationLine(profile, plot), [profile, plot]);
  const bands = useMemo(() => gradeBandShapes(profile, plot), [profile, plot]);
  const flow = useMemo(() => (flowY ? flowShapes(profile, x, flowY, flowY(0)) : []), [profile, x, flowY]);
  const flowEdge = useMemo(() => (flowY ? flowLine(profile, x, flowY) : ""), [profile, x, flowY]);
  const sections = useMemo(() => (kind === "stress" ? stripSections(route.stress_spans, total) : []), [kind, route.stress_spans, total]);
  const placed = useMemo(() => (mass ? placeCrossings(profile.crossings ?? [], x, LEFT, RIGHT) : []), [mass, profile.crossings, x]);

  const metresAt = (event: PointerEvent<HTMLDivElement>): number => {
    const box = event.currentTarget.getBoundingClientRect();
    const px = box.width > 0 ? ((event.clientX - box.left) / box.width) * WIDTH : LEFT;
    return Math.min(Math.max(((px - LEFT) / (RIGHT - LEFT)) * total, 0), total);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const next = positionAfterKey(event.key, at ?? 0, total);
    if (next === null) return;
    event.preventDefault();
    setHover(null);
    setAt(next);
  };

  const marker = reading.m;
  const markerX = x(marker);
  const elevAtMarker = reading.elevationM;
  const ridersAtMarker = reading.riders;
  const present = tiersPresent(sections);
  const tableName = kind === "mass" ? "Climbs and intersections as tables" : "Climbs as a table";
  const prompt = "Move along the chart, or use the arrow keys, to read the route at a point.";

  const defs = (
    <defs>
      {/* 8% or more: dark diagonal lines over the amber. */}
      <pattern id={`${uid}-hatch`} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <line x1="0" y1="0" x2="0" y2="5" stroke="#1b1e24" strokeWidth="2" />
      </pattern>
      {FLOW_BANDS.map((band) => (
        <pattern key={band.index} id={`${uid}-flow-${band.pattern}`} width="6" height="6" patternUnits="userSpaceOnUse">
          {band.pattern === "crosshatch" && <path d="M0 0L6 6M6 0L0 6" stroke={INK} strokeWidth="1.2" />}
          {band.pattern === "diagonal" && <path d="M-1 5L5 -1M2 8L8 2" stroke={DARK_INK} strokeWidth="1.4" />}
          {band.pattern === "dots" && <circle cx="3" cy="3" r="1.1" fill={INK} />}
          {band.pattern === "horizontal" && <path d="M0 1.5H6M0 4.5H6" stroke={INK} strokeWidth="1" />}
        </pattern>
      ))}
      {/* The tier styles' patterns, as the stress bar draws them (styles.css .stress-seg-N). */}
      <pattern id={`${uid}-t2`} width="8" height="12" patternUnits="userSpaceOnUse">
        <rect x="6" width="2" height="12" fill="rgba(255,255,255,0.4)" />
      </pattern>
      <pattern id={`${uid}-t3`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="2" height="6" fill="rgba(255,255,255,0.4)" />
      </pattern>
      <pattern id={`${uid}-t4`} width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
        <rect width="1.5" height="4" fill="rgba(255,255,255,0.4)" />
      </pattern>
    </defs>
  );

  return (
    <div className={`elevation-chart elevation-chart-${kind}`}>
      <p className="pc-summary" id={`${uid}-summary`}>
        {summary}
      </p>
      <div
        ref={slider}
        className="pc-plot"
        role="slider"
        tabIndex={0}
        aria-label={kind === "mass" ? "Elevation and riders per minute along the route" : "Elevation and stress along the route"}
        aria-orientation="horizontal"
        aria-valuemin={0}
        aria-valuemax={Math.round(total)}
        aria-valuenow={Math.round(marker)}
        aria-valuetext={reading.text}
        aria-describedby={`${uid}-summary ${uid}-keys`}
        onKeyDown={onKeyDown}
        onFocus={() => setAt((v) => v ?? 0)}
        onBlur={() => {
          setAt(null);
          setHover(null);
        }}
        onPointerMove={(event) => setHover(metresAt(event))}
        onPointerDown={(event) => setHover(metresAt(event))}
        onPointerLeave={() => setHover(null)}
        onPointerUp={(event) => {
          setAt(metresAt(event));
          if (event.pointerType !== "mouse") setHover(null);
        }}
        onPointerCancel={() => setHover(null)}
      >
        <svg viewBox={`0 0 ${WIDTH} ${layout.height}`} className="pc-svg" aria-hidden="true" focusable="false">
          {defs}
          {/* The elevation axis: top and bottom, feet first. */}
          <text className="pc-axis-text" x={2} y={elevTop + 8}>
            <tspan x={2}>{feet(range.hi)}</tspan>
            <tspan x={2} dy={10}>
              {metres(range.hi)}
            </tspan>
          </text>
          <text className="pc-axis-text" x={2} y={elevBottom - 10}>
            <tspan x={2}>{feet(range.lo)}</tspan>
            <tspan x={2} dy={10}>
              {metres(range.lo)}
            </tspan>
          </text>
          <line className="pc-axis" x1={LEFT} y1={elevBottom} x2={RIGHT} y2={elevBottom} />
          <path className="pc-area" d={area} />
          {bands.map((b, i) => (
            <path key={`${b.band}-${i}`} d={b.d} fill={GRADE_BAND_FILL} />
          ))}
          {bands
            .filter((b) => b.band === 2)
            .map((b, i) => (
              <path key={`hatch-${i}`} d={b.d} fill={`url(#${uid}-hatch)`} />
            ))}
          <path className="pc-line" d={line} fill="none" />

          {kind === "stress" && (
            <g>
              {sections.map((s, i) => {
                const cls = spanClass({ tier: s.tier, facility: null });
                const w = Math.max(x(s.to_m) - x(s.from_m), 0);
                return (
                  <g key={i}>
                    <rect x={x(s.from_m)} y={LAYOUT.stress.stripTop} width={w} height={LAYOUT.stress.stripBottom - LAYOUT.stress.stripTop} fill={cls.color} />
                    {s.tier === 2 && <rect x={x(s.from_m)} y={LAYOUT.stress.stripTop} width={w} height={12} fill={`url(#${uid}-t2)`} />}
                    {s.tier === 3 && <rect x={x(s.from_m)} y={LAYOUT.stress.stripTop} width={w} height={12} fill={`url(#${uid}-t3)`} />}
                    {s.tier === 4 && <rect x={x(s.from_m)} y={LAYOUT.stress.stripTop} width={w} height={12} fill={`url(#${uid}-t4)`} />}
                    {s.tier === 5 && w > 0 && <path d={crossHatch(x(s.from_m), LAYOUT.stress.stripTop, w, 12)} stroke={cls.halo} strokeWidth="1.6" fill="none" />}
                  </g>
                );
              })}
              <rect className="pc-strip-frame" x={LEFT} y={LAYOUT.stress.stripTop} width={RIGHT - LEFT} height={12} fill="none" />
            </g>
          )}

          {mass && flowY && (
            <g>
              <text className="pc-axis-text" x={2} y={mass.flowTop + 3}>
                {top}
              </text>
              <text className="pc-axis-text" x={2} y={mass.flowBottom}>
                0
              </text>
              <text className="pc-axis-text" x={2} y={(mass.flowTop + mass.flowBottom) / 2 - 2}>
                riders
              </text>
              <text className="pc-axis-text" x={2} y={(mass.flowTop + mass.flowBottom) / 2 + 9}>
                /min
              </text>
              <line className="pc-axis" x1={LEFT} y1={mass.flowBottom} x2={RIGHT} y2={mass.flowBottom} />
              {flow.map((shape, i) => (
                <g key={i}>
                  <path d={shape.d} fill={shape.band.color} fillOpacity={0.9} />
                  <path d={shape.d} fill={`url(#${uid}-flow-${shape.band.pattern})`} />
                </g>
              ))}
              <path className="pc-flow-edge" d={flowEdge} fill="none" />
              {FLOW_GUIDES.filter((g) => g.at < top).map((g) => (
                <g key={g.at}>
                  <line x1={LEFT} y1={flowY(g.at)} x2={RIGHT} y2={flowY(g.at)} stroke={g.color} strokeWidth="1.2" strokeDasharray="2 3" />
                  <text x={RIGHT} y={flowY(g.at) - 2} fill={g.color} className="pc-guide-text" textAnchor="end">
                    {g.at}
                  </text>
                </g>
              ))}
              {placed.map(({ crossing, x: cx, labelled, anchor, row, label }, i) => (
                <g key={i}>
                  <line className="pc-tick" x1={cx} y1={mass.markerY + 5} x2={cx} y2={mass.flowBottom} />
                  <CrossingMarker severity={crossing.severity} x={cx} y={mass.markerY} />
                  {labelled && (
                    <text className="pc-cross-text" x={cx} y={mass.labelY + row * 10} textAnchor={anchor}>
                      {label}
                    </text>
                  )}
                </g>
              ))}
            </g>
          )}

          {/* The distance axis. */}
          {[0, total / 2, total].map((m, i) => (
            <text key={i} className="pc-axis-text" x={x(m)} y={layout.axisY} textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"}>
              {axisDistance(m)}
            </text>
          ))}

          {/* The scrub marker: a line through every track, and a ring on the line it reads. */}
          {active !== null && (
            <g className="pc-marker">
              <line x1={markerX} y1={mass ? elevTop - 2 : elevTop - 2} x2={markerX} y2={mass ? mass.flowBottom : LAYOUT.stress.stripBottom + 2} strokeDasharray="3 2" />
              {elevAtMarker !== null && <circle cx={markerX} cy={plot.y(elevAtMarker)} r="3.5" />}
              {mass && flowY && ridersAtMarker !== null && <circle cx={markerX} cy={flowY(ridersAtMarker)} r="3.5" />}
            </g>
          )}
        </svg>
      </div>
      <p className="hint pc-keys" id={`${uid}-keys`}>
        Left and right arrow keys move along the route; Home and End go to the ends.
      </p>
      <p className="pc-readout" aria-hidden="true">
        {active === null ? prompt : reading.text}
      </p>
      <ul className="pc-legend" aria-label="Chart key">
        <li>
          <svg width="14" height="10" aria-hidden="true">
            <rect width="14" height="10" fill={GRADE_BAND_FILL} />
          </svg>
          {GRADE_BANDS[0].label}
        </li>
        <li>
          <svg width="14" height="10" aria-hidden="true">
            <rect width="14" height="10" fill={GRADE_BAND_FILL} />
            <path d="M0 10 L10 0 M4 10 L14 0" stroke="#1b1e24" strokeWidth="2" />
          </svg>
          {GRADE_BANDS[1].label}
        </li>
        {kind === "stress" ? (
          <li className="pc-legend-strip">Strip under the elevation: traffic stress along the route</li>
        ) : (
          FLOW_BANDS.map((band) => (
            <li key={band.index}>
              <svg width="14" height="10" aria-hidden="true">
                <rect width="14" height="10" fill={band.color} />
                <rect width="14" height="10" fill={`url(#${uid}-flow-${band.pattern})`} />
              </svg>
              {band.label}
            </li>
          ))
        )}
        {kind === "mass" && (
          <>
            <li>
              <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 2.5 22.5 20.5H1.5Z" fill={SEVERITY_COLOURS.orange.fill} stroke={SEVERITY_COLOURS.orange.stroke} strokeWidth="2" />
              </svg>
              Higher stress junction (triangle)
            </li>
            <li>
              <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 1.5 22.5 12 12 22.5 1.5 12Z" fill={SEVERITY_COLOURS.red.fill} stroke={SEVERITY_COLOURS.red.stroke} strokeWidth="2" />
              </svg>
              Very high stress junction (diamond)
            </li>
            <li>
              <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                <circle cx="12" cy="12" r="6" className="pc-dot" />
              </svg>
              Other major crossing (dot)
            </li>
          </>
        )}
      </ul>
      {kind === "stress" && present.length > 0 && (
        <ul className="pc-tiers" aria-label="Stress tiers on the strip">
          {present.map((tier) => {
            const cls = spanClass({ tier, facility: null });
            return (
              <li key={tier ?? "unknown"}>
                <span className={`swatch stress-seg-${tier ?? "unknown"}`} style={{ backgroundColor: cls.color, ["--seg-accent" as string]: cls.halo }} aria-hidden="true" />
                {tier === null ? "Not rated" : tier >= 5 ? "Avoid" : `LTS ${tier}`}
              </li>
            );
          })}
        </ul>
      )}
      <details className="pc-table-fold">
        <summary>{tableName}</summary>
        <Tables profile={profile} kind={kind} />
      </details>
    </div>
  );
}

function tiersPresent(sections: { tier: number | null }[]): (number | null)[] {
  const seen = new Set<number | null>();
  for (const s of sections) seen.add(s.tier);
  return [...seen].sort((a, b) => (a ?? 99) - (b ?? 99));
}

function feet(m: number): string {
  return elevationWords(m).split(" (")[0];
}

function metres(m: number): string {
  const text = elevationWords(m);
  return `(${text.split(" (")[1] ?? ""}`;
}

/** Cross-hatch lines for an Avoid section, clipped to the strip by being drawn inside it. */
function crossHatch(x0: number, y0: number, w: number, h: number): string {
  let d = "";
  for (let dx = -h; dx < w; dx += 6) {
    const a = Math.max(0, dx);
    const b = Math.min(w, dx + h);
    d += `M${x0 + a} ${y0 + (a - dx)} L${x0 + b} ${y0 + (b - dx)} `;
    d += `M${x0 + a} ${y0 + h - (a - dx)} L${x0 + b} ${y0 + h - (b - dx)} `;
  }
  return d;
}

function CrossingMarker({ severity, x, y }: { severity: "orange" | "red" | null; x: number; y: number }): ReactNode {
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

/** The climbs, and on a Mass Ride the intersections, as tables: the picture's text alternative. */
function Tables({ profile, kind }: { profile: RouteProfile; kind: ChartKind }) {
  const rows = climbRows(profile, kind);
  const crossings = kind === "mass" ? crossingRows(profile) : [];
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
      {kind === "mass" &&
        (crossings.length === 0 ? (
          <p className="hint">No major intersections on this route.</p>
        ) : (
          <div className="pc-table-wrap">
            <table className="pc-table">
              <caption>Major intersections, in the order ridden</caption>
              <thead>
                <tr>
                  <th scope="col">At</th>
                  <th scope="col">Street</th>
                  <th scope="col">Marker</th>
                  <th scope="col">Corkers</th>
                </tr>
              </thead>
              <tbody>
                {crossings.map((row, i) => (
                  <tr key={i}>
                    <th scope="row">{row.mile}</th>
                    <td>{row.street}</td>
                    <td>{row.marker}</td>
                    <td>{row.corkers}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </div>
  );
}
