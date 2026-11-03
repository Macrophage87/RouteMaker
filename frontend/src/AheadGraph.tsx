/**
 * The ride's graphs of the road ahead (lib/aheadGraph.ts; Stephen 2026-11-03): a short card at the foot of the ride
 * screen, the next 2 miles by traffic stress, elevation, or on a Mass Ride rider flow or corkers. The graphs that are on
 * stack under one strip of turns and junction markers, on one distance axis labelled once at the foot ("Have each
 * graph share the same x axis, so it only needs to be labeled once"). Drawn in SVG; the picture is hidden from screen
 * readers, which hear one sentence a graph instead. Not a control: More's bubbles choose the graphs.
 *
 * Stress bars are taller where stress is higher and carry their level, so colour is never the only cue; steep grades
 * are amber and hatched as on the route chart; turns are arrows, black, or orange on a triangle and red on a diamond
 * where the planner flagged the junction (the shapes of its junction markers); you are the triangle on the axis, and on
 * a shared ride each other rider a dot.
 */
import { Fragment, useId, useMemo } from "react";
import type { RouteResponse } from "./lib/api.ts";
import {
  AHEAD_GROUP,
  AHEAD_HEADING,
  AHEAD_NO_CORKERS,
  AHEAD_YOU,
  aheadWindow,
  axisTicks,
  barHeight,
  corkerMarks,
  corkerSentence,
  elevationSentence,
  elevationShape,
  flowSentence,
  flowSteps,
  flowTop,
  narrowest,
  ridersSentence,
  STRESS_TICKS,
  elevationTicks,
  flowTicks,
  shortStreet,
  stressBars,
  stressSentence,
  turnMarks,
  turnsSentence,
  type AheadView,
  type AheadWindow,
  type TurnMark,
} from "./lib/aheadGraph.ts";
import type { Cue } from "./lib/navigate.ts";
import { SEVERITY_COLOURS } from "./lib/intersectionMarkers.ts";
import { ROUTE_AVOID_MAGENTA } from "./lib/avoidColour.ts";
import { GRADE_BAND_FILL } from "./lib/profileChart.ts";

/** The drawing's size, in viewBox units (about pixels on a phone). */
const W = 320;
/** The strip of turns at the top. */
const TURNS_H = 26;
/** Each graph: its name, then its plot. */
const LABEL_H = 14;
const PLOT_H = 52;
const GAP = 4;
const AXIS_H = 22;
/** Room on the left for the y axis's labels ("450 ft"). */
const LEFT = 46;
const RIGHT = 8;

interface Props {
  views: readonly AheadView[];
  route: Pick<RouteResponse, "profile" | "stress_spans">;
  /** The ride's cues, for the turns strip. */
  cues: readonly Pick<Cue, "kind" | "atM" | "movement" | "severity">[];
  /** You, metres along the route. */
  youM: number;
  lengthM: number;
  /** The other riders on the line, metres along (a shared ride). */
  ridersAlong?: readonly number[];
}

/** Where a graph's plot sits in the drawing. */
interface Panel {
  top: number;
  h: number;
}

export function AheadGraph({ views, route, cues, youM, lengthM, ridersAlong = [] }: Props) {
  const id = useId();
  // Redrawn each 10 m, not each fix.
  const step = Math.floor(youM / 10) * 10;
  const ridersKey = ridersAlong.map((m) => Math.round(m / 10)).join(",");
  const w = useMemo(() => aheadWindow(step, lengthM, ridersAlong), [step, lengthM, ridersKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const x = (m: number) => LEFT + ((m - w.fromM) / (w.toM - w.fromM)) * (W - LEFT - RIGHT);
  const turns = useMemo(() => turnMarks(cues, w), [cues, w]);
  const panels = useMemo(() => {
    const drawn: { view: AheadView; panel: Panel; drawn: Drawn }[] = [];
    let at = TURNS_H;
    for (const view of views) {
      const panel = { top: at + LABEL_H, h: PLOT_H };
      const one = draw(view, route, w, x, panel);
      if (!one) continue;
      drawn.push({ view, panel, drawn: one });
      at = panel.top + panel.h + GAP;
    }
    return { drawn, base: at - GAP };
  }, [views, route, w]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!panels.drawn.length) return null;
  const { base } = panels;
  const H = base + AXIS_H;
  const riders = ridersSentence(w);
  const said = [turnsSentence(turns, w.youM), ...panels.drawn.map((p) => `${AHEAD_HEADING[p.view]}: ${p.drawn.sentence}`), riders].filter(Boolean).join(" ");
  return (
    <figure className="ride-ahead" role="group" aria-label={AHEAD_GROUP}>
      <p className="visually-hidden">{said}</p>
      <svg className="ride-ahead-plot" viewBox={`0 0 ${W} ${H}`} aria-hidden="true" focusable="false">
        <defs>
          <pattern id={`${id}-steep`} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="5" height="5" fill={GRADE_BAND_FILL} />
            <line x1="0" y1="0" x2="0" y2="5" className="ride-ahead-hatch" />
          </pattern>
        </defs>
        <Turns marks={turns} x={x} />
        {panels.drawn.map(({ view, panel, drawn }) => (
          <Fragment key={view}>
            <text className="ride-ahead-name" x={LEFT} y={panel.top - 3}>
              {AHEAD_HEADING[view]}
            </text>
            {drawn.body(`${id}-steep`)}
            <YAxis ticks={drawn.yTicks} panel={panel} />
          </Fragment>
        ))}
        <Axis w={w} x={x} base={base} top={TURNS_H} />
      </svg>
    </figure>
  );
}

/** A turn's arrow, drawn about a point, pointing up the screen and off to its side; left ones are right ones mirrored. */
const ARROWS: Record<NonNullable<TurnMark["movement"]>, { d: string; flip: boolean }> = {
  right: { d: "M-5 7V-1H4M1-5l4 4-4 4", flip: false },
  left: { d: "M-5 7V-1H4M1-5l4 4-4 4", flip: true },
  bear_right: { d: "M-3 7V2L3-4M-1-5h5v5", flip: false },
  bear_left: { d: "M-3 7V2L3-4M-1-5h5v5", flip: true },
  uturn: { d: "M3 7V-1a3.5 3.5 0 0 0-7 0v4M-7 0l3 3 3-3", flip: false },
};

/** The strip of turns and junction markers, over the graphs on the same scale. */
function Turns({ marks, x }: { marks: readonly TurnMark[]; x: X }) {
  const cy = TURNS_H / 2;
  return (
    <g className="ride-ahead-turns">
      {marks.map((mark, i) => {
        const cx = x(mark.m);
        const colour = mark.severity === "orange" || mark.severity === "red" ? SEVERITY_COLOURS[mark.severity] : null;
        // The planner's own shapes: an orange triangle, a red diamond; Avoid a magenta square.
        const shape =
          mark.severity === "orange" ? (
            <path d={`M${cx} ${cy - 11}l10.5 19h-21z`} fill={colour?.fill} stroke={colour?.stroke} strokeWidth={1.5} />
          ) : mark.severity === "red" ? (
            <path d={`M${cx} ${cy - 11}l11 11-11 11-11-11z`} fill={colour?.fill} stroke={colour?.stroke} strokeWidth={1.5} />
          ) : mark.severity === "avoid" ? (
            <rect x={cx - 9} y={cy - 9} width={18} height={18} fill={ROUTE_AVOID_MAGENTA} stroke="#1c1917" strokeWidth={1.5} />
          ) : null;
        if (!mark.movement) return <g key={i}>{shape}</g>;
        const arrow = ARROWS[mark.movement];
        return (
          <g key={i}>
            {shape}
            <g transform={`translate(${cx} ${cy + (shape ? 2 : 0)}) scale(${arrow.flip ? -1 : 1} 1)`}>
              <path className={shape ? "ride-ahead-arrow-on" : "ride-ahead-arrow"} d={arrow.d} />
            </g>
          </g>
        );
      })}
    </g>
  );
}

/** The y axis: its line and each label beside its tick, right-aligned in the gutter. */
function YAxis({ ticks, panel }: { ticks: readonly YTick[]; panel: Panel }) {
  if (!ticks.length) return null;
  return (
    <g className="ride-ahead-axis ride-ahead-y">
      <line x1={LEFT} x2={LEFT} y1={panel.top} y2={panel.top + panel.h} />
      {ticks.map((tick) => (
        <g key={tick.label}>
          <line x1={LEFT - 4} x2={LEFT} y1={tick.y} y2={tick.y} />
          <text x={LEFT - 6} y={tick.y + 4} textAnchor="end">
            {tick.label}
          </text>
        </g>
      ))}
    </g>
  );
}

interface YTick {
  y: number;
  label: string;
}

type X = (m: number) => number;

/** The one distance axis, under the last graph; a faint line up from you through every graph. */
function Axis({ w, x, base, top }: { w: AheadWindow; x: X; base: number; top: number }) {
  const you = x(w.youM);
  return (
    <g className="ride-ahead-axis">
      <line className="ride-ahead-you-line" x1={you} x2={you} y1={top} y2={base} />
      <line x1={LEFT} x2={W - RIGHT} y1={base} y2={base} />
      {axisTicks(w).filter((tick) => Math.abs(x(tick.m) - you) >= 26).map((tick) => {
        const at = x(tick.m);
        const end = at > W - 30;
        return (
          <g key={tick.m}>
            <line x1={at} x2={at} y1={base} y2={base + 4} />
            <text x={end ? W - 2 : at} y={base + 16} textAnchor={end ? "end" : "middle"}>
              {tick.label}
            </text>
          </g>
        );
      })}
      {w.riders.map((m, i) => (
        <circle key={i} className="ride-ahead-rider" cx={x(m)} cy={base} r={4.5} />
      ))}
      <path className="ride-ahead-you" d={`M${you} ${base - 1} l-6 9 h12 z`} />
      <text className="ride-ahead-you-word" x={Math.min(W - 16, Math.max(16, you))} y={base + 18} textAnchor="middle">
        {AHEAD_YOU}
      </text>
    </g>
  );
}

interface Drawn {
  sentence: string;
  yTicks: YTick[];
  body: (hatch: string) => React.ReactNode;
}

function draw(view: AheadView, route: Props["route"], w: AheadWindow, x: X, panel: Panel): Drawn | null {
  const profile = route.profile ?? null;
  const TOP = panel.top;
  const PLOT_H = panel.h;
  const y = (f: number) => TOP + PLOT_H * (1 - f);
  if (view === "stress") {
    if (!route.stress_spans) return null;
    const bars = stressBars(route.stress_spans, w);
    if (!bars.length) return null;
    return {
      sentence: stressSentence(bars, w.youM),
      yTicks: STRESS_TICKS.map((tick) => ({ y: y(barHeight(tick.level)), label: tick.label })),
      body: () =>
        bars.map((b) => {
          const left = x(b.fromM);
          const width = x(b.toM) - left;
          const top = y(barHeight(b.level));
          const short = TOP + PLOT_H - top < 20;
          return (
            <g key={b.fromM}>
              <rect className="ride-ahead-bar" x={left} y={top} width={width} height={TOP + PLOT_H - top} fill={b.color} />
              {width >= b.label.length * 8 + 6 && (
                // On a bar too short to hold it, the number sits just above the bar, in the text colour.
                <text className="ride-ahead-level" x={left + width / 2} y={short ? top - 3 : top + 15} textAnchor="middle" style={short ? undefined : { fill: b.ink }}>
                  {b.label}
                </text>
              )}
            </g>
          );
        }),
    };
  }
  if (!profile) return null;
  if (view === "elevation") {
    const shape = elevationShape(profile, w);
    if (!shape) return null;
    const ey = (e: number) => y(0.04 + ((e - shape.lowM) / (shape.highM - shape.lowM)) * 0.8);
    const line = shape.points.map(([m, e], i) => `${i ? "L" : "M"}${x(m).toFixed(1)} ${ey(e).toFixed(1)}`).join(" ");
    const base = TOP + PLOT_H;
    const under = (from: number, to: number) => {
      const inside = shape.points.filter(([m]) => m >= from && m <= to);
      if (inside.length < 2) return "";
      return `M${x(inside[0][0])} ${base} ${inside.map(([m, e]) => `L${x(m).toFixed(1)} ${ey(e).toFixed(1)}`).join(" ")} L${x(inside[inside.length - 1][0])} ${base} Z`;
    };
    // The label names the steepest stretch ahead of you, as the sentence does.
    const ahead = shape.steep.filter((s) => s.toM > w.youM);
    const steepest = ahead.length ? ahead.reduce((a, b) => (b.gradePct > a.gradePct ? b : a)) : null;
    return {
      sentence: elevationSentence(shape, w),
      yTicks: elevationTicks(shape.lowM, shape.highM).map((tick) => ({ y: ey(tick.m), label: tick.label })),
      body: (hatch) => (
        <>
          <path className="ride-ahead-ground" d={under(w.fromM, w.toM)} />
          {shape.steep.map((s) => (
            <path key={s.fromM} d={under(s.fromM, s.toM)} fill={s.band === 2 ? `url(#${hatch})` : GRADE_BAND_FILL} className={`ride-ahead-steep-${s.band}`} />
          ))}
          <path className="ride-ahead-line" d={line} />
          {steepest && x(steepest.toM) - x(steepest.fromM) >= 10 && (
            <text className="ride-ahead-grade" x={(x(steepest.fromM) + x(steepest.toM)) / 2} y={base - 6} textAnchor="middle">
              {Math.round(steepest.gradePct)}%
            </text>
          )}
        </>
      ),
    };
  }
  if (view === "flow") {
    const steps = flowSteps(profile, w);
    if (!steps.length) return null;
    const top = flowTop(steps);
    const fy = (r: number) => y(Math.min(1, r / top) * 0.82);
    const low = narrowest(steps, w.youM);
    return {
      sentence: flowSentence(steps, w.youM),
      yTicks: flowTicks(top).map((r) => ({ y: fy(r), label: String(r) })),
      body: () => (
        <>
          {steps.map((s) => (
            <rect key={s.fromM} x={x(s.fromM)} y={fy(s.riders)} width={Math.max(0.5, x(s.toM) - x(s.fromM))} height={TOP + PLOT_H - fy(s.riders)} fill={s.color} shapeRendering="crispEdges" />
          ))}
          {flowTicks(top).map((r) => (
            <line key={r} className="ride-ahead-guide" x1={LEFT} x2={W - RIGHT} y1={fy(r)} y2={fy(r)} />
          ))}
          {low && (
            <g className="ride-ahead-narrowest">
              <path d={`M${x((low.fromM + low.toM) / 2)} ${fy(low.riders) - 2} l-5 -8 h10 z`} />
              <text x={Math.min(W - 60, Math.max(40, x((low.fromM + low.toM) / 2)))} y={TOP + 10} textAnchor="middle">
                {Math.round(low.riders)}
              </text>
            </g>
          )}
        </>
      ),
    };
  }
  const marks = corkerMarks(profile, w);
  const sentence = corkerSentence(marks, w.youM, profile.crossings_complete !== false);
  return {
    sentence,
    yTicks: [],
    body: () =>
      !marks.length ? (
        <text className="ride-ahead-none" x={W / 2} y={TOP + PLOT_H / 2 + 5} textAnchor="middle">
          {AHEAD_NO_CORKERS}
        </text>
      ) : marks.map((c, i) => {
        const at = x(c.m);
        const right = at > W * 0.6;
        // Three rows in turn, so a long street name does not run into the next marker's.
        const row = TOP + 10 + (i % 3) * 16;
        return (
          <g key={c.m} className="ride-ahead-corker">
            <line x1={at} x2={at} y1={TOP + PLOT_H} y2={row + 8} />
            <circle cx={at} cy={row} r={8} />
            <text className="ride-ahead-corker-n" x={at} y={row + 4.5} textAnchor="middle">
              {c.corkers}
            </text>
            {c.street && (
              <text className="ride-ahead-street" x={right ? at - 12 : at + 12} y={row + 4.5} textAnchor={right ? "end" : "start"}>
                {shortStreet(c.street)}
              </text>
            )}
          </g>
        );
      }),
  };
}
