/**
 * A Mass Ride's route charts: three charts on one distance axis, each with its own heading, in the
 * owner's order (2026-10-10: "Have 3 charts for mass ride: Riders per minute, Corker load, Elevation.
 * They should all be there."; 147: "visualize rider flow, elevation, and anticipated corker
 * requirements over the route").
 *
 * - Riders per minute: the grade-adjusted riders a minute, filled in the spectral band colours (each
 *   also with a pattern), dotted guides at 60, 120 and 200, the narrowest point marked with a caret
 *   and its figure (147), and the stretches marked Avoid (325: no carrying capacity).
 * - Corker load: the junctions needing corkers in the half mile (0.8 km) around each point, per mile
 *   (lib/profileChart.ts `corkerLoad`, the default until a ride size is known), a tick at each such
 *   junction, the junction markers and their names (333, 396), and the stretches not checked.
 * - Elevation: the elevation line and area, with the 5% to 8% and 8%-or-more grades in amber, dotted
 *   and hatched.
 *
 * Each chart is a group named by its heading, with its summary before it and a slider for its
 * picture, whose value text is that chart's sentence at the keyboard's position. The three sliders
 * share one position, so moving along one moves the others' markers and the map's (`onScrub`), and
 * Tab from one to the next carries on at the same mile. The tables (climbs, bottlenecks, and the
 * intersections with the corker load at each) are behind one fold under the charts.
 */
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import type { RouteProfile, RouteResponse } from "./lib/api.ts";
import type { LonLat } from "./lib/geo.ts";
import { formatAxisPerMile } from "./lib/format.ts";
import {
  AVOID_FILL,
  AVOID_FRAME,
  AVOID_INK,
  AVOID_MIN_WIDTH,
  CHART_TYPE,
  FLOW_BANDS,
  FLOW_GUIDES,
  GRADE_BANDS,
  GRADE_BAND_FILL,
  MASS_CHARTS,
  avoidLabel,
  axisDistance,
  axisLength,
  bottleneckMark,
  corkerArea,
  corkerAt,
  corkerLine,
  corkerLoad,
  corkerTop,
  corkerWindowWords,
  elevationArea,
  elevationLine,
  elevationRange,
  flowLine,
  flowShapes,
  gradeBandShapes,
  jumpTargets,
  linear,
  lonLatAt,
  massReadings,
  massSummaries,
  placeCrossings,
  positionAfterKey,
  readingAt,
  ridersTop,
  type MassChartKey,
  type Plot,
} from "./lib/profileChart.ts";
import { AvoidPattern, CrossingMarker, FlowPatterns, GradePatterns, JunctionKey, LEFT, RIGHT, Tables, WIDTH, feet, metres } from "./chartParts.tsx";

/** Each chart's vertical layout, in viewBox units: its plot's top and bottom, and the distance axis's line of text. */
const LAYOUT = {
  riders: { height: 124, top: 16, bottom: 98, axisY: 116 },
  corkers: { height: 136, markerY: 9, top: 22, bottom: 82, labelY: 95, axisY: 128 },
  elevation: { height: 104, top: 10, bottom: 78, axisY: 96 },
} as const;

export function MassRideCharts({
  route,
  profile,
  onScrub,
}: {
  route: RouteResponse;
  profile: RouteProfile;
  /** The map point under the scrub, or null when there is none (the chart lost it). */
  onScrub?: (point: LonLat | null) => void;
}) {
  const uid = useId().replace(/[^A-Za-z0-9_-]/g, "");
  const total = axisLength(route, profile);
  // One position for the three sliders: the keyboard's (or a click's), kept when the focus leaves, so
  // coming back (or Tab to the next chart) carries on from there (a11y N2).
  const [at, setAt] = useState<number | null>(null);
  const [focused, setFocused] = useState<MassChartKey | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const active = hover ?? (focused ? at : null);
  const load = useMemo(() => corkerLoad(profile, total), [profile, total]);
  const reading = useMemo(() => readingAt(route, profile, active ?? at ?? 0, "mass"), [route, profile, active, at]);
  const shown = useMemo(() => massReadings(route, profile, load, active ?? at ?? 0), [route, profile, load, active, at]);
  // What a screen reader hears: the keyboard's position only (a11y S3).
  const spoken = useMemo(() => massReadings(route, profile, load, at ?? 0), [route, profile, load, at]);
  const spokenM = useMemo(() => readingAt(route, profile, at ?? 0, "mass").m, [route, profile, at]);
  const summaries = useMemo(() => massSummaries(route, profile, load), [route, profile, load]);
  const targets = useMemo(() => jumpTargets(profile), [profile]);
  const heard = useRef(onScrub);
  heard.current = onScrub;

  useEffect(() => {
    if (!heard.current) return;
    heard.current(active === null ? null : lonLatAt(route.geometry.coordinates, reading.m, total));
  }, [active, reading.m, route, total]);
  useEffect(() => () => heard.current?.(null), []);

  const x = useMemo(() => linear(0, total, LEFT, RIGHT), [total]);
  const markerX = x(reading.m);

  const metresAt = (event: PointerEvent<HTMLDivElement>): number => {
    const box = event.currentTarget.getBoundingClientRect();
    const px = box.width > 0 ? ((event.clientX - box.left) / box.width) * WIDTH : LEFT;
    return Math.min(Math.max(((px - LEFT) / (RIGHT - LEFT)) * total, 0), total);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const next = positionAfterKey(event.key, at ?? 0, total, targets, event.shiftKey);
    if (next === null) return;
    event.preventDefault();
    setHover(null);
    setAt(next);
  };
  const keys =
    "Arrow keys move along the route; Page Up and Page Down move further; Home and End go to the ends; C and Shift+C go to the next and previous climb, I and Shift+I to the next and previous intersection. The three charts share one position.";
  const prompt = "Move along the chart, or use the arrow keys, to read the route at a point.";

  const slider = (key: MassChartKey, name: string, height: number, body: ReactNode, defs: ReactNode) => (
    <div
      className="pc-plot"
      role="slider"
      tabIndex={0}
      aria-label={name}
      aria-orientation="horizontal"
      aria-valuemin={0}
      aria-valuemax={Math.round(total)}
      aria-valuenow={Math.round(spokenM)}
      aria-valuetext={spoken[key]}
      aria-describedby={`${uid}-keys`}
      onKeyDown={onKeyDown}
      onFocus={() => {
        setFocused(key);
        setAt((v) => v ?? 0);
      }}
      onBlur={() => {
        setFocused(null);
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
      <svg viewBox={`0 0 ${WIDTH} ${height}`} className="pc-svg" aria-hidden="true" focusable="false">
        <defs>{defs}</defs>
        {body}
        {/* The distance axis, the same on all three. */}
        {[0, total / 2, total].map((m, i) => (
          <text key={i} className="pc-axis-text" x={x(m)} y={LAYOUT[key].axisY} textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"}>
            {axisDistance(m)}
          </text>
        ))}
      </svg>
    </div>
  );

  const charts: Record<MassChartKey, { picture: ReactNode; legend: ReactNode }> = {
    riders: ridersChart({ uid: `${uid}r`, profile, x, active, markerX, riders: reading.riders, slider }),
    corkers: corkerChart({ uid: `${uid}c`, profile, load, x, total, active, markerX, at: reading.m, slider }),
    elevation: elevationOnly({ uid: `${uid}e`, profile, x, active, markerX, elevation: reading.elevationM, slider }),
  };

  return (
    <div className="elevation-chart elevation-chart-mass">
      {MASS_CHARTS.map((c) => (
        <div key={c.key} className={`pc-chart pc-chart-${c.key}`} role="group" aria-labelledby={`${uid}-${c.key}-h`}>
          <h4 className="pc-chart-heading" id={`${uid}-${c.key}-h`}>
            {c.heading}
          </h4>
          <p className="pc-summary">{summaries[c.key]}</p>
          {charts[c.key].picture}
          <p className="pc-readout" aria-hidden="true">
            {active !== null ? shown[c.key] : c.key === "riders" ? prompt : ""}
          </p>
          <ul className="pc-legend" aria-label={`${c.heading} key`}>
            {charts[c.key].legend}
          </ul>
        </div>
      ))}
      <p className="hint pc-keys" id={`${uid}-keys`}>
        {keys}
      </p>
      <p className="hint pc-source">
        Riders per minute: estimated from road widths (in DC, DC Open Data, Roadway Block, CC BY 4.0, adapted; elsewhere OpenStreetMap) and DC Bike Party counts; indicative (level roads about ±25%; hill adjustment not yet checked). Corker load: the major intersections that cross or join an LTS 3 or worse road, counted over the {corkerWindowWords()} around each point; how many corkers each needs is not estimated yet. Elevation: USGS 3DEP.
      </p>
      <details className="pc-table-fold">
        <summary>Climbs, bottlenecks and intersections as tables</summary>
        <Tables profile={profile} kind="mass" spans={route.stress_spans} total={total} load={load} />
      </details>
    </div>
  );
}

type Slider = (key: MassChartKey, name: string, height: number, body: ReactNode, defs: ReactNode) => ReactNode;

const NAMES = Object.fromEntries(MASS_CHARTS.map((c) => [c.key, c.name])) as Record<MassChartKey, string>;

/** The scrub's line down a chart, and a ring on the value it reads. */
function Marker({ x, top, bottom, ring }: { x: number; top: number; bottom: number; ring: number | null }): ReactNode {
  return (
    <g className="pc-marker">
      <line x1={x} y1={top - 2} x2={x} y2={bottom} strokeDasharray="3 2" />
      {ring !== null && <circle cx={x} cy={ring} r="3.5" />}
    </g>
  );
}

/** An Avoid (or not-checked) block's left edge and width: at least AVOID_MIN_WIDTH wide, centred on its stretch, inside the plot. */
function blockSpan(x: (m: number) => number, from: number, to: number): { x0: number; w: number } {
  const real = Math.max(x(to) - x(from), 0);
  const w = Math.max(real, AVOID_MIN_WIDTH);
  return { x0: Math.min(Math.max(x(from) - (w - real) / 2, LEFT), RIGHT - w), w };
}

function ridersChart({
  uid,
  profile,
  x,
  active,
  markerX,
  riders,
  slider,
}: {
  uid: string;
  profile: RouteProfile;
  x: (m: number) => number;
  active: number | null;
  markerX: number;
  riders: number | null;
  slider: Slider;
}): { picture: ReactNode; legend: ReactNode } {
  const L = LAYOUT.riders;
  const top = ridersTop(profile);
  const y = linear(0, top, L.bottom, L.top);
  const flow = flowShapes(profile, x, y, y(0));
  const edge = flowLine(profile, x, y);
  const narrowest = bottleneckMark(profile, x, y, LEFT, RIGHT);
  const avoid = profile.avoid ?? [];
  const body = (
    <>
      <text className="pc-axis-text" x={2} y={L.top + 4}>
        {top}
      </text>
      <text className="pc-axis-text" x={2} y={L.bottom}>
        0
      </text>
      <text className="pc-axis-text" x={2} y={(L.top + L.bottom) / 2 - 2}>
        riders
      </text>
      <text className="pc-axis-text" x={2} y={(L.top + L.bottom) / 2 + 10}>
        /min
      </text>
      <line className="pc-axis" x1={LEFT} y1={L.bottom} x2={RIGHT} y2={L.bottom} />
      {flow.map((shape, i) => (
        <g key={i}>
          <path d={shape.d} fill={shape.band.color} fillOpacity={0.9} />
          <path d={shape.d} fill={`url(#${uid}-flow-${shape.band.pattern})`} />
        </g>
      ))}
      {avoid.map((r, i) => {
        const { x0, w } = blockSpan(x, r.from_m, r.to_m);
        const h = L.bottom - L.top;
        return (
          <g key={`avoid-${i}`} className="pc-avoid">
            <rect x={x0} y={L.top} width={w} height={h} fill={AVOID_FILL} />
            <rect x={x0} y={L.top} width={w} height={h} fill={`url(#${uid}-avoid)`} />
            {/* The two-tone frame: near-black outside, white inside, so one of them is 3:1 from whatever it touches. */}
            <rect className="pc-avoid-frame" x={x0 - 0.5} y={L.top - 0.5} width={w + 1} height={h + 1} fill="none" stroke={AVOID_FRAME} strokeWidth="1" />
            <rect className="pc-avoid-inner" x={x0 + 0.5} y={L.top + 0.5} width={Math.max(w - 1, 0)} height={h - 1} fill="none" stroke={AVOID_INK} strokeWidth="1" />
            <text className="pc-avoid-text" x={x0 + w / 2} y={(L.top + L.bottom) / 2 + 4} textAnchor="middle">
              {avoidLabel(w)}
            </text>
          </g>
        );
      })}
      <path className="pc-flow-edge" d={edge} fill="none" />
      {FLOW_GUIDES.filter((g) => g.at < top).map((g) => {
        const label = String(g.at);
        const textW = label.length * 6.2;
        return (
          <g key={g.at}>
            <line className={`pc-guide pc-guide-${g.band}`} x1={LEFT} y1={y(g.at)} x2={RIGHT} y2={y(g.at)} />
            <rect className="pc-guide-swatch" x={RIGHT - textW - 11} y={y(g.at) - 8} width={8} height={5} fill={g.color} />
            <text x={RIGHT} y={y(g.at) - 2} className="pc-guide-text" textAnchor="end">
              {label}
            </text>
          </g>
        );
      })}
      {narrowest && (
        <g className="pc-narrowest">
          <path d={`M${narrowest.x - 5} ${narrowest.y - 11} L${narrowest.x + 5} ${narrowest.y - 11} L${narrowest.x} ${narrowest.y - 2} Z`} />
          <text
            className="pc-narrowest-text"
            x={narrowest.anchor === "start" ? LEFT : narrowest.anchor === "end" ? RIGHT : narrowest.x}
            y={narrowest.y - 14 >= L.top + 9 ? narrowest.y - 14 : narrowest.y + 13}
            textAnchor={narrowest.anchor}
          >
            {narrowest.label}
          </text>
        </g>
      )}
      {active !== null && <Marker x={markerX} top={L.top} bottom={L.bottom} ring={riders !== null ? y(riders) : null} />}
    </>
  );
  const defs = (
    <>
      <FlowPatterns uid={uid} />
      <AvoidPattern uid={uid} />
    </>
  );
  const legend = (
    <>
      {FLOW_BANDS.map((band) => (
        <li key={band.index}>
          <svg width="14" height="10" aria-hidden="true">
            <rect width="14" height="10" fill={band.color} />
            <rect width="14" height="10" fill={`url(#${uid}-flow-${band.pattern})`} />
          </svg>
          {band.label}
        </li>
      ))}
      {avoid.length > 0 && (
        <li>
          <svg width="14" height="10" aria-hidden="true" className="pc-avoid-key">
            <rect width="14" height="10" fill={AVOID_FILL} />
            <rect width="14" height="10" fill={`url(#${uid}-avoid)`} />
            <rect x="0.5" y="0.5" width="13" height="9" fill="none" stroke={AVOID_INK} strokeWidth="1" />
          </svg>
          Marked Avoid (A where narrow): no capacity given
        </li>
      )}
      {narrowest && (
        <li>
          <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3 5H21L12 20Z" className="pc-narrowest-key" />
          </svg>
          Narrowest with the hills (downward triangle)
        </li>
      )}
    </>
  );
  return { picture: slider("riders", NAMES.riders, L.height, body, defs), legend };
}

function corkerChart({
  uid,
  profile,
  load,
  x,
  total,
  active,
  markerX,
  at,
  slider,
}: {
  uid: string;
  profile: RouteProfile;
  load: ReturnType<typeof corkerLoad>;
  x: (m: number) => number;
  total: number;
  active: number | null;
  markerX: number;
  at: number;
  slider: Slider;
}): { picture: ReactNode; legend: ReactNode } {
  const L = LAYOUT.corkers;
  const top = load ? corkerTop(load) : 4;
  const y = linear(0, top, L.bottom, L.top);
  const crossings = profile.crossings ?? [];
  const placed = placeCrossings(crossings, x, LEFT, RIGHT);
  const unchecked = !load ? [] : (profile.unchecked ?? []).filter((r) => r.to_m > r.from_m && r.from_m < total);
  const noTick = crossings.some((c) => !c.corkers_needed);
  const body = (
    <>
      {/* The side: the top figure per mile, per km under it, and 0. */}
      <text className="pc-axis-text" x={2} y={L.top + 4}>
        <tspan x={2}>{formatAxisPerMile(top)[0]}</tspan>
        <tspan x={2} dy={CHART_TYPE}>{formatAxisPerMile(top)[1]}</tspan>
      </text>
      <text className="pc-axis-text" x={2} y={L.bottom}>
        0
      </text>
      <line className="pc-axis" x1={LEFT} y1={L.bottom} x2={RIGHT} y2={L.bottom} />
      {load && <line className="pc-corker-half" x1={LEFT} y1={y(top / 2)} x2={RIGHT} y2={y(top / 2)} />}
      {load ? (
        <>
          <path className="pc-corker-area" d={corkerArea(load, x, y, L.bottom)} />
          <path className="pc-corker-line" d={corkerLine(load, x, y)} fill="none" />
        </>
      ) : (
        <text className="pc-unchecked-text pc-corker-none" x={(LEFT + RIGHT) / 2} y={(L.top + L.bottom) / 2 + 4} textAnchor="middle">
          Intersections not checked
        </text>
      )}
      {unchecked.map((r, i) => {
        const { x0, w } = blockSpan(x, r.from_m, Math.min(r.to_m, total));
        const h = L.bottom - L.top;
        return (
          <g key={`unchecked-${i}`} className="pc-unchecked">
            <rect x={x0} y={L.top} width={w} height={h} className="pc-unchecked-fill" />
            <rect x={x0} y={L.top} width={w} height={h} fill={`url(#${uid}-unchecked)`} />
            <rect className="pc-unchecked-frame" x={x0} y={L.top} width={w} height={h} fill="none" />
            <text className="pc-unchecked-text" x={x0 + w / 2} y={(L.top + L.bottom) / 2 + 4} textAnchor="middle">
              {w >= 70 ? "NOT CHECKED" : "?"}
            </text>
          </g>
        );
      })}
      {placed.map(({ crossing, x: cx, labelled, anchor, row, label }, i) => (
        <g key={i}>
          {crossing.corkers_needed && <line className="pc-tick pc-corker-tick" x1={cx} y1={L.markerY + 6} x2={cx} y2={L.bottom} />}
          <CrossingMarker severity={crossing.severity} x={cx} y={L.markerY} />
          {labelled && (
            <text className="pc-cross-text" x={cx} y={L.labelY + row * CHART_TYPE} textAnchor={anchor}>
              {label}
            </text>
          )}
        </g>
      ))}
      {active !== null && <Marker x={markerX} top={L.top} bottom={L.bottom} ring={load ? y(corkerAt(load, at).perMile) : null} />}
    </>
  );
  const defs = (
    <pattern id={`${uid}-unchecked`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <line x1="0" y1="0" x2="0" y2="6" className="pc-unchecked-hatch" strokeWidth="1.5" />
    </pattern>
  );
  const legend = !load ? (
    <li>Intersections were not checked, so there is no corker load to draw</li>
  ) : (
    <>
      <li>
        <svg width="14" height="10" aria-hidden="true">
          <path d="M0 10V6H5V2H10V6H14V10Z" className="pc-corker-area" />
          <path d="M0 6H5V2H10V6H14" className="pc-corker-line" fill="none" />
        </svg>
        Junctions needing corkers per mile (per km), over the {corkerWindowWords()} around each point
      </li>
      <li>
        <svg width="14" height="10" viewBox="0 0 14 10" aria-hidden="true">
          <path d="M7 0V10" className="pc-tick pc-corker-tick" />
        </svg>
        Tick: a junction needing corkers
      </li>
      {crossings.length > 0 && <JunctionKey />}
      {noTick && <li>A marker with no tick: no corkers needed</li>}
      {unchecked.length > 0 && (
        <li>
          <svg width="14" height="10" aria-hidden="true">
            <rect width="14" height="10" className="pc-unchecked-fill" />
            <rect width="14" height="10" fill={`url(#${uid}-unchecked)`} />
          </svg>
          Hatched grey: not checked for intersections (? where narrow)
        </li>
      )}
    </>
  );
  return { picture: slider("corkers", NAMES.corkers, L.height, body, defs), legend };
}

function elevationOnly({
  uid,
  profile,
  x,
  active,
  markerX,
  elevation,
  slider,
}: {
  uid: string;
  profile: RouteProfile;
  x: (m: number) => number;
  active: number | null;
  markerX: number;
  elevation: number | null;
  slider: Slider;
}): { picture: ReactNode; legend: ReactNode } {
  const L = LAYOUT.elevation;
  const range = elevationRange(profile);
  const plot: Plot = { x, y: linear(range.lo, range.hi, L.bottom, L.top), left: LEFT, right: RIGHT, top: L.top, bottom: L.bottom };
  const body = (
    <>
      {/* The elevation axis: top and bottom, feet first. */}
      <text className="pc-axis-text" x={2} y={L.top + 8}>
        <tspan x={2}>{feet(range.hi)}</tspan>
        <tspan x={2} dy={CHART_TYPE}>
          {metres(range.hi)}
        </tspan>
      </text>
      <text className="pc-axis-text" x={2} y={L.bottom - 11}>
        <tspan x={2}>{feet(range.lo)}</tspan>
        <tspan x={2} dy={CHART_TYPE}>
          {metres(range.lo)}
        </tspan>
      </text>
      <line className="pc-axis" x1={LEFT} y1={L.bottom} x2={RIGHT} y2={L.bottom} />
      <path className="pc-area" d={elevationArea(profile, plot)} />
      {gradeBandShapes(profile, plot).map((b, i) => (
        <g key={`${b.band}-${i}`}>
          <path d={b.d} fill={GRADE_BAND_FILL} />
          <path d={b.d} fill={`url(#${uid}-${b.band === 2 ? "hatch" : "dots"})`} className={`pc-band-${b.band}`} />
        </g>
      ))}
      <path className="pc-line" d={elevationLine(profile, plot)} fill="none" />
      {active !== null && <Marker x={markerX} top={L.top} bottom={L.bottom} ring={elevation !== null ? plot.y(elevation) : null} />}
    </>
  );
  const legend = GRADE_BANDS.map((band) => (
    <li key={band.band}>
      <svg width="14" height="10" aria-hidden="true">
        <rect width="14" height="10" fill={GRADE_BAND_FILL} />
        <rect width="14" height="10" fill={`url(#${uid}-${band.pattern})`} />
      </svg>
      {band.label}
    </li>
  ));
  return { picture: slider("elevation", NAMES.elevation, L.height, body, <GradePatterns uid={uid} />), legend };
}
