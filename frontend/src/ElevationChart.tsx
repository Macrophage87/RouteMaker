/**
 * The route's elevation chart (OWNER-DECISIONS 322, 323; mockup v3, Route "Elevation and stress").
 * Drawn here in SVG from the API's `profile`, with no chart library. A Mass Ride has three charts
 * instead (the owner, 2026-10-10: "Riders per minute, Corker load, Elevation"), in MassRideCharts.tsx.
 *
 * Every ride type but Mass Ride: distance across (miles, kilometres in brackets), elevation up (feet,
 * metres in brackets), the 5% to 8% and 8%-or-more grades picked out in amber (dotted, and hatched,
 * so colour is not the only cue), and under it the rolling stress chart (460.12, 461d, 461e): calm
 * miles per actual mile over the mile around each point, junctions included, on a log scale, the area
 * filled in the map's tier colours and the stress bar's patterns between guides at the API's
 * band edges, a faint step line of each stretch's own figure, Avoid stretches in the magenta, and the
 * flagged junctions' markers. Where the API sends no score (an older answer), the rolling stress strip
 * of 322 in the map's styles stands in.
 *
 * The scrub. Hovering or touching moves a marker on the map (`onScrub`), and so does the keyboard:
 * the plot is a slider, whose arrow keys step along the route and whose value text is the spoken
 * sentence ("Mile 4.2: elevation 310 ft (94 m), grade 6%, LTS 2"). The value text follows the
 * keyboard's (or a click's) position only, never the hover, so a focused screen reader is not
 * flooded by a moving mouse. A text alternative stands beside the picture: a summary, and the climbs
 * as a table. Everything it says is made in lib/profileChart.ts.
 */
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import type { RouteProfile, RouteResponse } from "./lib/api.ts";
import type { LonLat } from "./lib/geo.ts";
import {
  AVOID_FILL,
  AVOID_FRAME,
  AVOID_INK,
  AVOID_MIN_WIDTH,
  CALM_BANDS,
  CHART_TYPE,
  GRADE_BANDS,
  GRADE_BAND_FILL,
  avoidLabel,
  axisDistance,
  axisLength,
  calmAvoid,
  calmFigure,
  calmLine,
  calmScale,
  calmShapes,
  calmSource,
  calmStepLine,
  calmTicks,
  calmTop,
  chartKind,
  elevationArea,
  elevationLine,
  elevationRange,
  gradeBandShapes,
  jumpTargets,
  linear,
  lonLatAt,
  positionAfterKey,
  readingAt,
  sectionWords,
  stripKey,
  stripSections,
  summaryText,
  usableCalm,
  type Plot,
  type StripSection,
} from "./lib/profileChart.ts";
import { spanClass } from "./lib/routeColours.ts";
import { AvoidPattern, CrossingMarker, GradePatterns, JunctionKey, LEFT, RIGHT, Tables, WIDTH, capitalise, feet, metres } from "./chartParts.tsx";
import { MassRideCharts } from "./MassRideCharts.tsx";

/** The vertical layout of each chart, in viewBox units. */
const LAYOUT = {
  stress: { height: 152, elevTop: 10, elevBottom: 98, stripTop: 108, stripBottom: 120, axisY: 140 },
  calm: { height: 202, elevTop: 10, elevBottom: 84, markerY: 95, calmTop: 106, calmBottom: 166, axisY: 188 },
} as const;

interface ChartProps {
  route: RouteResponse;
  profile: RouteProfile;
  /** The map point under the scrub, or null when there is none (the chart lost it). */
  onScrub?: (point: LonLat | null) => void;
  /** A Mass Ride's anticipated ride size, riders (the corker load's group length). */
  rideSize?: number;
}

/** The route chart: a Mass Ride's three charts, or every other ride type's elevation and stress. */
export function ElevationChart(props: ChartProps) {
  return chartKind(props.route) === "mass" ? <MassRideCharts {...props} /> : <StressChart {...props} />;
}

function StressChart({ route, profile, onScrub }: ChartProps) {
  const kind = "stress" as const;
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

  const calm = useMemo(() => usableCalm(profile), [profile]);
  const layout = calm ? LAYOUT.calm : LAYOUT.stress;
  const range = useMemo(() => elevationRange(profile), [profile]);
  const elevTop = layout.elevTop;
  const elevBottom = layout.elevBottom;
  const x = useMemo(() => linear(0, total, LEFT, RIGHT), [total]);
  const plot: Plot = useMemo(
    () => ({ x, y: linear(range.lo, range.hi, elevBottom, elevTop), left: LEFT, right: RIGHT, top: elevTop, bottom: elevBottom }),
    [x, range, elevTop, elevBottom],
  );

  const area = useMemo(() => elevationArea(profile, plot), [profile, plot]);
  const line = useMemo(() => elevationLine(profile, plot), [profile, plot]);
  const bands = useMemo(() => gradeBandShapes(profile, plot), [profile, plot]);
  const sections = useMemo(() => (!calm ? stripSections(route.stress_spans, total) : []), [calm, route.stress_spans, total]);
  const calmLayout = calm ? LAYOUT.calm : null;
  const calmMax = useMemo(() => (calm ? calmTop(calm) : 1), [calm]);
  const calmY = useMemo(() => (calmLayout ? calmScale(calmMax, calmLayout.calmBottom, calmLayout.calmTop) : null), [calmLayout, calmMax]);
  const calmArea = useMemo(() => (calm && calmY && calmLayout ? calmShapes(profile, calm, x, calmY, calmLayout.calmBottom) : []), [profile, calm, x, calmY, calmLayout]);
  const calmEdge = useMemo(() => (calm && calmY ? calmLine(profile, calm, x, calmY) : ""), [profile, calm, x, calmY]);
  const calmSteps = useMemo(() => (calm && calmY ? calmStepLine(calm, x, calmY, total) : ""), [calm, x, calmY, total]);
  const calmAvoids = useMemo(() => (calm ? calmAvoid(calm, total) : []), [calm, total]);
  const calmMarks = calm ? calm.points.filter((p) => p.kind === "junction" && p.severity !== null && p.m <= total) : [];

  const metresAt = (event: PointerEvent<HTMLDivElement>): number => {
    const box = event.currentTarget.getBoundingClientRect();
    const px = box.width > 0 ? ((event.clientX - box.left) / box.width) * WIDTH : LEFT;
    return Math.min(Math.max(((px - LEFT) / (RIGHT - LEFT)) * total, 0), total);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const next = positionAfterKey(event.key, at ?? 0, total, { climbs: targets.climbs }, event.shiftKey);
    if (next === null) return;
    event.preventDefault();
    setHover(null);
    setAt(next);
  };

  const markerX = x(reading.m);
  const elevAtMarker = reading.elevationM;
  const present = stripKey(sections);
  const tableName = calm ? "Climbs and rolling stress as tables" : "Climbs as a table";
  const prompt = "Move along the chart, or use the arrow keys, to read the route at a point.";
  const keys = "Arrow keys move along the route; Page Up and Page Down move further; Home and End go to the ends; C and Shift+C go to the next and previous climb.";

  const defs = (
    <defs>
      <GradePatterns uid={uid} />
      {/* Avoid on the rolling stress track (397): dark chevrons on magenta. */}
      <AvoidPattern uid={uid} />
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
        aria-label={calm ? "Elevation and rolling stress along the route" : "Elevation and stress along the route"}
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

          {calm && calmY && calmLayout && (
            <g>
              {/* The side: the unit on the marker row (nothing else is drawn left of the plot there), and the log scale's figures, right-aligned against the plot and never crowded. */}
              <text className="pc-axis-text" x={2} y={calmLayout.markerY - 6}>
                calm mi
              </text>
              <text className="pc-axis-text" x={2} y={calmLayout.markerY - 6 + CHART_TYPE}>
                per mi
              </text>
              {calmTicks(calmMax, calmY).map((t) => (
                <text key={t} className="pc-axis-text" x={LEFT - 3} y={calmY(t) + 4} textAnchor="end">
                  {t}
                </text>
              ))}
              <line className="pc-axis" x1={LEFT} y1={calmLayout.calmBottom} x2={RIGHT} y2={calmLayout.calmBottom} />
              <line className="pc-calm-one" x1={LEFT} y1={calmY(1)} x2={RIGHT} y2={calmY(1)} />
              {calmArea.map((shape, i) => {
                const cls = spanClass({ tier: shape.band.tier, facility: "none" });
                return (
                  <g key={i}>
                    <path d={shape.d} fill={cls.color} fillOpacity={0.9} />
                    <path d={shape.d} fill={`url(#${uid}-t${shape.band.tier})`} />
                  </g>
                );
              })}
              <path className="pc-calm-steps-casing" d={calmSteps} fill="none" />
              <path className="pc-calm-steps" d={calmSteps} fill="none" />
              {calmAvoids.map((r, i) => {
                const real = Math.max(x(r.to_m) - x(r.from_m), 0);
                const w = Math.max(real, AVOID_MIN_WIDTH);
                const x0 = Math.min(Math.max(x(r.from_m) - (w - real) / 2, LEFT), RIGHT - w);
                const h = 12;
                const y0 = calmLayout.calmBottom - h;
                return (
                  <g key={`calm-avoid-${i}`} className="pc-avoid">
                    <rect x={x0} y={y0} width={w} height={h} fill={AVOID_FILL} />
                    <rect x={x0} y={y0} width={w} height={h} fill={`url(#${uid}-avoid)`} />
                    <rect className="pc-avoid-frame" x={x0 - 0.5} y={y0 - 0.5} width={w + 1} height={h + 1} fill="none" stroke={AVOID_FRAME} strokeWidth="1" />
                    <rect className="pc-avoid-inner" x={x0 + 0.5} y={y0 + 0.5} width={Math.max(w - 1, 0)} height={h - 1} fill="none" stroke={AVOID_INK} strokeWidth="1" />
                    <text className="pc-avoid-text" x={x0 + w / 2} y={y0 + 10} textAnchor="middle">
                      {avoidLabel(w)}
                    </text>
                  </g>
                );
              })}
              <path className="pc-calm-line" d={calmEdge} fill="none" />
              {calm.bands.slice(0, 2).map((at, i) => {
                if (at >= calmMax) return null;
                // Where both edges are one (0 on the slider: LTS 3 costs nothing extra), only the LTS 4 guide is drawn.
                if (i === 0 && calm.bands[1] !== undefined && at >= calm.bands[1]) return null;
                const label = `LTS ${i + 3} from ${calmFigure(at)}`;
                const textW = label.length * 6.2;
                const tier = i + 3;
                const cls = spanClass({ tier, facility: "none" });
                return (
                  <g key={i}>
                    <line className="pc-calm-guide-casing" x1={LEFT} y1={calmY(at)} x2={RIGHT} y2={calmY(at)} />
                    <line className="pc-calm-guide" x1={LEFT} y1={calmY(at)} x2={RIGHT} y2={calmY(at)} />
                    <rect x={RIGHT - textW - 13} y={calmY(at) - 9} width={10} height={7} fill={cls.color} />
                    <rect className="pc-calm-swatch" x={RIGHT - textW - 13} y={calmY(at) - 9} width={10} height={7} fill={`url(#${uid}-t${tier})`} />
                    <text x={RIGHT} y={calmY(at) - 2} className="pc-guide-text" textAnchor="end">
                      {label}
                    </text>
                  </g>
                );
              })}
              {calmMarks.map((p, i) => (
                <CrossingMarker key={i} severity={p.severity} x={x(p.m)} y={calmLayout.markerY} />
              ))}
            </g>
          )}

          {!calm && (
            <g>
              {sections.map((s, i) => (
                <StripRect key={i} section={s} x0={x(s.from_m)} w={Math.max(x(s.to_m) - x(s.from_m), 0)} uid={uid} />
              ))}
              <rect className="pc-strip-frame" x={LEFT} y={LAYOUT.stress.stripTop} width={RIGHT - LEFT} height={12} fill="none" />
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
              <line x1={markerX} y1={elevTop - 2} x2={markerX} y2={calmLayout ? calmLayout.calmBottom : LAYOUT.stress.stripBottom + 2} strokeDasharray="3 2" />
              {elevAtMarker !== null && <circle cx={markerX} cy={plot.y(elevAtMarker)} r="3.5" />}
              {calmY && reading.calm !== null && <circle cx={markerX} cy={calmY(reading.calm)} r="3.5" />}
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
        {calm ? (
          <>
            <li className="pc-legend-strip">
              Under the elevation: rolling stress{calm.estimate ? " (an estimate)" : ""}, calm miles per mile (calm km per km) over the mile around each point, on a log scale (1 to 2 is as tall as 5 to 10); about 1 is all quiet streets
            </li>
            {CALM_BANDS.map((band) => {
              const cls = spanClass({ tier: band.tier, facility: "none" });
              return (
                <li key={band.index}>
                  <svg width="14" height="10" aria-hidden="true">
                    <rect width="14" height="10" fill={cls.color} />
                    <rect width="14" height="10" fill={`url(#${uid}-t${band.tier})`} />
                  </svg>
                  {band.label}
                </li>
              );
            })}
            <li>
              <svg width="14" height="10" aria-hidden="true">
                <path d="M0 7H5V3H14" className="pc-calm-steps" fill="none" />
              </svg>
              Dashed steps: each stretch's own figure, without the mile around it
            </li>
            <li>
              <svg width="14" height="10" aria-hidden="true">
                <path d="M0 5H14" className="pc-calm-guide" fill="none" />
              </svg>
              Dotted lines: where the levels change (the solid grey line is 1)
            </li>
            {calmAvoids.length > 0 && (
              <li>
                <svg width="14" height="10" aria-hidden="true" className="pc-avoid-key">
                  <rect width="14" height="10" fill={AVOID_FILL} />
                  <rect width="14" height="10" fill={`url(#${uid}-avoid)`} />
                  <rect x="0.5" y="0.5" width="13" height="9" fill="none" stroke={AVOID_INK} strokeWidth="1" />
                </svg>
                Avoid (A where narrow)
              </li>
            )}
            <JunctionKey orange={calmMarks.some((p) => p.severity === "orange")} red={calmMarks.some((p) => p.severity === "red")} dot={false} />
          </>
        ) : (
          <li className="pc-legend-strip">Strip under the elevation: traffic stress along the route</li>
        )}
      </ul>
      {!calm && present.length > 0 && (
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
      <p className="hint pc-source">{calm ? `Elevation: USGS 3DEP. ${calmSource(calm)}` : "Elevation: USGS 3DEP."}</p>
      <details className="pc-table-fold">
        <summary>{tableName}</summary>
        <Tables profile={profile} kind={kind} spans={route.stress_spans} total={total} />
      </details>
    </div>
  );
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
