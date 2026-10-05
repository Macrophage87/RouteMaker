/**
 * The route's elevation chart (OWNER-DECISIONS 322, 323; mockup v3, Route "Elevation and stress"),
 * and the Mass Ride version of it (328, 329, 332, 333, 396; mockup v3, Mass Ride). Drawn here in SVG
 * from the API's `profile`, with no chart library.
 *
 * - Every ride type but Mass Ride: distance across (miles, kilometres in brackets), elevation up
 *   (feet, metres in brackets), the 5% to 8% and 8%-or-more grades picked out in amber (dotted, and
 *   hatched, so colour is not the only cue), and a rolling stress strip under it in the map's styles
 *   (a traffic-free path and an unpaved stretch as the map draws them).
 * - Mass Ride: in place of the strip, a filled area of the grade-adjusted riders a minute in the
 *   spectral band colours (each also with a pattern), dotted guides at 60, 120 and 200, its own
 *   axis, the narrowest point marked with a caret and its figure (147), the stretches marked Avoid
 *   (325: no carrying capacity), and the major intersections as ticks, names and the junction markers.
 *
 * The scrub. Hovering or touching moves a marker on the map (`onScrub`), and so does the keyboard:
 * the plot is a slider, whose arrow keys step along the route and whose value text is the spoken
 * sentence ("Mile 4.2: elevation 310 ft (94 m), grade 6%, LTS 2"). The value text follows the
 * keyboard's (or a click's) position only, never the hover, so a focused screen reader is not
 * flooded by a moving mouse. A text alternative stands beside the picture: a summary, and the climbs
 * (and, on a Mass Ride, the bottlenecks and intersections) as tables. Everything it says is made in
 * lib/profileChart.ts.
 */
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import type { RouteProfile, RouteResponse } from "./lib/api.ts";
import type { LonLat } from "./lib/geo.ts";
import { SEVERITY_COLOURS } from "./lib/intersectionMarkers.ts";
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
  PARTIAL_JUNCTIONS,
  avoidLabel,
  axisDistance,
  axisLength,
  bottleneckMark,
  bottleneckRows,
  chartKind,
  climbRows,
  crossingCaption,
  crossingRows,
  crossingsPartial,
  elevationArea,
  elevationLine,
  elevationRange,
  elevationWords,
  flowLine,
  flowShapes,
  gradeBandShapes,
  jumpTargets,
  linear,
  lonLatAt,
  placeCrossings,
  positionAfterKey,
  readingAt,
  ridersTop,
  sectionWords,
  stripSections,
  summaryText,
  type ChartKind,
  type Plot,
  type StripSection,
} from "./lib/profileChart.ts";
import { spanClass } from "./lib/routeColours.ts";

const WIDTH = 360;
const LEFT = 46;
const RIGHT = WIDTH - 8;

/** The vertical layout of each chart, in viewBox units. */
const LAYOUT = {
  stress: { height: 152, elevTop: 10, elevBottom: 98, stripTop: 108, stripBottom: 120, axisY: 140 },
  mass: { height: 212, elevTop: 12, elevBottom: 66, markerY: 79, flowTop: 94, flowBottom: 150, labelY: 163, axisY: 204 },
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
  // The keyboard's (or a click's) position: kept when the chart loses the focus, so coming back
  // carries on from there (a11y N2). `focused` says whether its marker shows.
  const [at, setAt] = useState<number | null>(null);
  const [focused, setFocused] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const active = hover ?? (focused ? at : null);
  const reading = useMemo(() => readingAt(route, profile, active ?? at ?? 0, kind), [route, profile, active, at, kind]);
  // What a screen reader hears: the keyboard's position only (a11y S3).
  const spoken = useMemo(() => readingAt(route, profile, at ?? 0, kind), [route, profile, at, kind]);
  const summary = useMemo(() => summaryText(route, profile, kind), [route, profile, kind]);
  const targets = useMemo(() => jumpTargets(profile), [profile]);
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
  const narrowest = useMemo(() => (flowY ? bottleneckMark(profile, x, flowY, LEFT, RIGHT) : null), [profile, x, flowY]);
  const avoid = mass ? (profile.avoid ?? []) : [];

  const metresAt = (event: PointerEvent<HTMLDivElement>): number => {
    const box = event.currentTarget.getBoundingClientRect();
    const px = box.width > 0 ? ((event.clientX - box.left) / box.width) * WIDTH : LEFT;
    return Math.min(Math.max(((px - LEFT) / (RIGHT - LEFT)) * total, 0), total);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const next = positionAfterKey(event.key, at ?? 0, total, kind === "mass" ? targets : { climbs: targets.climbs }, event.shiftKey);
    if (next === null) return;
    event.preventDefault();
    setHover(null);
    setAt(next);
  };

  const markerX = x(reading.m);
  const elevAtMarker = reading.elevationM;
  const ridersAtMarker = reading.riders;
  const present = classesPresent(sections);
  const tableName = kind === "mass" ? "Climbs, bottlenecks and intersections as tables" : "Climbs as a table";
  const prompt = "Move along the chart, or use the arrow keys, to read the route at a point.";
  const keys =
    kind === "mass"
      ? "Arrow keys move along the route; Page Up and Page Down move further; Home and End go to the ends; C and Shift+C go to the next and previous climb, I and Shift+I to the next and previous intersection."
      : "Arrow keys move along the route; Page Up and Page Down move further; Home and End go to the ends; C and Shift+C go to the next and previous climb.";

  const defs = (
    <defs>
      {/* 5% to 8%: sparse dark dots over the amber (the a11y review's S2: the amber alone is 1.3:1 on the light theme's grey). */}
      <pattern id={`${uid}-dots`} width="4" height="4" patternUnits="userSpaceOnUse">
        <circle cx="2" cy="2" r="0.8" fill="#1b1e24" fillOpacity="0.75" />
      </pattern>
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
      {/* Avoid on the riders track (397): dark chevrons on magenta, a texture of its own, not the bottleneck's cross-hatch. */}
      <pattern id={`${uid}-avoid`} width="8" height="6" patternUnits="userSpaceOnUse">
        <path d="M0 5L4 1L8 5" stroke={AVOID_FRAME} strokeOpacity="0.7" strokeWidth="1.3" fill="none" />
      </pattern>
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
      {/* Unpaved: the map's dotted mark over the brown (OWNER-DECISIONS 302). */}
      <pattern id={`${uid}-unpaved`} width="5" height="6" patternUnits="userSpaceOnUse">
        <circle cx="2.5" cy="3" r="1" fill="rgba(255,255,255,0.75)" />
      </pattern>
    </defs>
  );

  return (
    <div className={`elevation-chart elevation-chart-${kind}`}>
      <p className="pc-summary" id={`${uid}-summary`}>
        {summary}
      </p>
      <div
        className="pc-plot"
        role="slider"
        tabIndex={0}
        aria-label={kind === "mass" ? "Elevation and riders per minute along the route" : "Elevation and stress along the route"}
        aria-orientation="horizontal"
        aria-valuemin={0}
        aria-valuemax={Math.round(total)}
        aria-valuenow={Math.round(spoken.m)}
        aria-valuetext={spoken.text}
        aria-describedby={`${uid}-keys`}
        onKeyDown={onKeyDown}
        onFocus={() => {
          setFocused(true);
          setAt((v) => v ?? 0);
        }}
        onBlur={() => {
          setFocused(false);
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
            <tspan x={2} dy={CHART_TYPE}>
              {metres(range.hi)}
            </tspan>
          </text>
          <text className="pc-axis-text" x={2} y={elevBottom - 11}>
            <tspan x={2}>{feet(range.lo)}</tspan>
            <tspan x={2} dy={CHART_TYPE}>
              {metres(range.lo)}
            </tspan>
          </text>
          <line className="pc-axis" x1={LEFT} y1={elevBottom} x2={RIGHT} y2={elevBottom} />
          <path className="pc-area" d={area} />
          {bands.map((b, i) => (
            <g key={`${b.band}-${i}`}>
              <path d={b.d} fill={GRADE_BAND_FILL} />
              <path d={b.d} fill={`url(#${uid}-${b.band === 2 ? "hatch" : "dots"})`} className={`pc-band-${b.band}`} />
            </g>
          ))}
          <path className="pc-line" d={line} fill="none" />

          {kind === "stress" && (
            <g>
              {sections.map((s, i) => (
                <StripRect key={i} section={s} x0={x(s.from_m)} w={Math.max(x(s.to_m) - x(s.from_m), 0)} uid={uid} />
              ))}
              <rect className="pc-strip-frame" x={LEFT} y={LAYOUT.stress.stripTop} width={RIGHT - LEFT} height={12} fill="none" />
            </g>
          )}

          {mass && flowY && (
            <g>
              <text className="pc-axis-text" x={2} y={mass.flowTop + 4}>
                {top}
              </text>
              <text className="pc-axis-text" x={2} y={mass.flowBottom}>
                0
              </text>
              <text className="pc-axis-text" x={2} y={(mass.flowTop + mass.flowBottom) / 2 - 2}>
                riders
              </text>
              <text className="pc-axis-text" x={2} y={(mass.flowTop + mass.flowBottom) / 2 + 10}>
                /min
              </text>
              <line className="pc-axis" x1={LEFT} y1={mass.flowBottom} x2={RIGHT} y2={mass.flowBottom} />
              {flow.map((shape, i) => (
                <g key={i}>
                  <path d={shape.d} fill={shape.band.color} fillOpacity={0.9} />
                  <path d={shape.d} fill={`url(#${uid}-flow-${shape.band.pattern})`} />
                </g>
              ))}
              {avoid.map((r, i) => {
                // At least AVOID_MIN_WIDTH wide, centred on the stretch, so a short one keeps its "A" (397, a11y re-review).
                const real = Math.max(x(r.to_m) - x(r.from_m), 0);
                const w = Math.max(real, AVOID_MIN_WIDTH);
                const x0 = Math.min(Math.max(x(r.from_m) - (w - real) / 2, LEFT), RIGHT - w);
                const h = mass.flowBottom - mass.flowTop;
                return (
                  <g key={`avoid-${i}`} className="pc-avoid">
                    <rect x={x0} y={mass.flowTop} width={w} height={h} fill={AVOID_FILL} />
                    <rect x={x0} y={mass.flowTop} width={w} height={h} fill={`url(#${uid}-avoid)`} />
                    {/* The two-tone frame: near-black outside, white inside, so one of them is 3:1 from whatever it touches. */}
                    <rect className="pc-avoid-frame" x={x0 - 0.5} y={mass.flowTop - 0.5} width={w + 1} height={h + 1} fill="none" stroke={AVOID_FRAME} strokeWidth="1" />
                    <rect className="pc-avoid-inner" x={x0 + 0.5} y={mass.flowTop + 0.5} width={Math.max(w - 1, 0)} height={h - 1} fill="none" stroke={AVOID_INK} strokeWidth="1" />
                    <text className="pc-avoid-text" x={x0 + w / 2} y={(mass.flowTop + mass.flowBottom) / 2 + 4} textAnchor="middle">
                      {avoidLabel(w)}
                    </text>
                  </g>
                );
              })}
              <path className="pc-flow-edge" d={flowEdge} fill="none" />
              {FLOW_GUIDES.filter((g) => g.at < top).map((g) => {
                const label = String(g.at);
                const textW = label.length * 6.2;
                return (
                  <g key={g.at}>
                    <line className={`pc-guide pc-guide-${g.band}`} x1={LEFT} y1={flowY(g.at)} x2={RIGHT} y2={flowY(g.at)} />
                    <rect className="pc-guide-swatch" x={RIGHT - textW - 11} y={flowY(g.at) - 8} width={8} height={5} fill={g.color} />
                    <text x={RIGHT} y={flowY(g.at) - 2} className="pc-guide-text" textAnchor="end">
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
                    y={narrowest.y - 14 >= mass.flowTop + 9 ? narrowest.y - 14 : narrowest.y + 13}
                    textAnchor={narrowest.anchor}
                  >
                    {narrowest.label}
                  </text>
                </g>
              )}
              {placed.map(({ crossing, x: cx, labelled, anchor, row, label }, i) => (
                <g key={i}>
                  <line className="pc-tick" x1={cx} y1={mass.markerY + 5} x2={cx} y2={mass.flowBottom} />
                  <CrossingMarker severity={crossing.severity} x={cx} y={mass.markerY} />
                  {labelled && (
                    <text className="pc-cross-text" x={cx} y={mass.labelY + row * CHART_TYPE} textAnchor={anchor}>
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
              <line x1={markerX} y1={elevTop - 2} x2={markerX} y2={mass ? mass.flowBottom : LAYOUT.stress.stripBottom + 2} strokeDasharray="3 2" />
              {elevAtMarker !== null && <circle cx={markerX} cy={plot.y(elevAtMarker)} r="3.5" />}
              {mass && flowY && ridersAtMarker !== null && <circle cx={markerX} cy={flowY(ridersAtMarker)} r="3.5" />}
            </g>
          )}
        </svg>
      </div>
      <p className="hint pc-keys" id={`${uid}-keys`}>
        {keys}
      </p>
      <p className="pc-readout" aria-hidden="true">
        {active === null ? prompt : reading.text}
      </p>
      <ul className="pc-legend" aria-label="Chart key">
        {GRADE_BANDS.map((band) => (
          <li key={band.band}>
            <svg width="14" height="10" aria-hidden="true">
              <rect width="14" height="10" fill={GRADE_BAND_FILL} />
              <rect width="14" height="10" fill={`url(#${uid}-${band.pattern})`} />
            </svg>
            {band.label}
          </li>
        ))}
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
            {avoid.length > 0 && (
              <li>
                <svg width="14" height="10" aria-hidden="true" className="pc-avoid-key">
                  <rect width="14" height="10" fill={AVOID_FILL} />
                  <rect width="14" height="10" fill={`url(#${uid}-avoid)`} />
                  <rect x="0.5" y="0.5" width="13" height="9" fill="none" stroke={AVOID_INK} strokeWidth="1" />
                </svg>
                Avoid (A where narrow): no carrying capacity
              </li>
            )}
            {narrowest && (
              <li>
                <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M3 5H21L12 20Z" className="pc-narrowest-key" />
                </svg>
                Narrowest point (downward triangle)
              </li>
            )}
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
              Busy road crossed or joined (dot)
            </li>
          </>
        )}
      </ul>
      {kind === "stress" && present.length > 0 && (
        <ul className="pc-tiers" aria-label="Stress on the strip">
          {present.map((s) => {
            const cls = spanClass(s);
            return (
              <li key={cls.key}>
                <span
                  className={`swatch ${s.unpaved ? "pc-swatch-unpaved" : s.tier === 5 ? "stress-seg-5" : s.facility === "path" ? "" : `stress-seg-${s.tier ?? "unknown"}`}`}
                  style={{ backgroundColor: cls.color, ["--seg-accent" as string]: cls.halo }}
                  aria-hidden="true"
                />
                {capitalise(sectionWords(s) ?? "not rated")}
              </li>
            );
          })}
        </ul>
      )}
      <p className="hint pc-source">
        {kind === "mass"
          ? "Elevation: USGS 3DEP. Riders per minute: estimated from OpenStreetMap lane counts and DC Bike Party counts; indicative (level roads about ±25%; hill adjustment not yet checked)."
          : "Elevation: USGS 3DEP."}
      </p>
      <details className="pc-table-fold">
        <summary>{tableName}</summary>
        <Tables profile={profile} kind={kind} spans={route.stress_spans} />
      </details>
    </div>
  );
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The strip's sections by the map's class (spanClass: unpaved, path, tier), one of each, in tier order. */
function classesPresent(sections: StripSection[]): StripSection[] {
  const seen = new Map<string, StripSection>();
  for (const s of sections) {
    const key = spanClass(s).key;
    if (!seen.has(key)) seen.set(key, s);
  }
  const rank = (s: StripSection) => (s.facility === "path" && s.tier !== 5 ? 0 : (s.tier ?? 99)) + (s.unpaved ? 0.5 : 0);
  return [...seen.values()].sort((a, b) => rank(a) - rank(b));
}

/** One section of the stress strip, in the map's colour for it, with the tier's pattern (or the unpaved dots). */
function StripRect({ section: s, x0, w, uid }: { section: StripSection; x0: number; w: number; uid: string }): ReactNode {
  const cls = spanClass(s);
  const y = LAYOUT.stress.stripTop;
  const h = LAYOUT.stress.stripBottom - LAYOUT.stress.stripTop;
  const plain = s.facility !== "path" && !s.unpaved;
  // Avoid keeps its cross-hatch on a path too: spanClass draws a path rated Avoid in the magenta (r3 N3).
  const avoid = !s.unpaved && s.tier === 5;
  return (
    <g>
      <rect x={x0} y={y} width={w} height={h} fill={cls.color} />
      {s.unpaved && <rect x={x0} y={y} width={w} height={h} fill={`url(#${uid}-unpaved)`} />}
      {plain && s.tier === 2 && <rect x={x0} y={y} width={w} height={h} fill={`url(#${uid}-t2)`} />}
      {plain && s.tier === 3 && <rect x={x0} y={y} width={w} height={h} fill={`url(#${uid}-t3)`} />}
      {plain && s.tier === 4 && <rect x={x0} y={y} width={w} height={h} fill={`url(#${uid}-t4)`} />}
      {avoid && w > 0 && <path d={crossHatch(x0, y, w, h)} stroke={cls.halo} strokeWidth="1.6" fill="none" />}
    </g>
  );
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

/** The climbs, and on a Mass Ride the bottlenecks and the intersections, as tables: the picture's text alternative. */
function Tables({ profile, kind, spans }: { profile: RouteProfile; kind: ChartKind; spans: RouteResponse["stress_spans"] }) {
  const rows = climbRows(profile, kind, spans);
  const bottlenecks = kind === "mass" ? bottleneckRows(profile) : [];
  const crossings = kind === "mass" ? crossingRows(profile) : [];
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
