/**
 * The ride's graph of the road ahead (lib/aheadGraph.ts; Stephen 2026-11-03): a short card at the foot of the ride
 * screen, the next 2 miles by traffic stress, elevation, or on a Mass Ride rider flow or corkers. Drawn in SVG; the
 * picture is hidden from screen readers, which hear its heading and one sentence instead. Not a control: More's
 * bubbles choose the graph.
 *
 * Stress bars are taller where stress is higher and carry their level, so colour is never the only cue; steep grades
 * are amber and hatched as on the route chart; you are the triangle, and on a shared ride each other rider a dot.
 */
import { useId, useMemo } from "react";
import type { RouteResponse } from "./lib/api.ts";
import {
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
  shortStreet,
  stressBars,
  stressSentence,
  type AheadView,
  type AheadWindow,
} from "./lib/aheadGraph.ts";
import { FLOW_GUIDES, GRADE_BAND_FILL } from "./lib/profileChart.ts";

/** The drawing's size, in viewBox units (about pixels on a phone). */
const W = 320;
const PLOT_H = 64;
const TOP = 6;
const AXIS_H = 20;
const H = TOP + PLOT_H + AXIS_H;
const LEFT = 6;
const RIGHT = 6;

interface Props {
  view: AheadView;
  route: Pick<RouteResponse, "profile" | "stress_spans">;
  /** You, metres along the route. */
  youM: number;
  lengthM: number;
  /** The other riders on the line, metres along (a shared ride). */
  ridersAlong?: readonly number[];
}

export function AheadGraph({ view, route, youM, lengthM, ridersAlong = [] }: Props) {
  const id = useId();
  // Redrawn each 10 m, not each fix.
  const step = Math.floor(youM / 10) * 10;
  const ridersKey = ridersAlong.map((m) => Math.round(m / 10)).join(",");
  const w = useMemo(() => aheadWindow(step, lengthM, ridersAlong), [step, lengthM, ridersKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const x = (m: number) => LEFT + ((m - w.fromM) / (w.toM - w.fromM)) * (W - LEFT - RIGHT);
  const y = (f: number) => TOP + PLOT_H * (1 - f);
  const drawn = useMemo(() => draw(view, route, w, x, y), [view, route, w]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!drawn) return null;
  const riders = ridersSentence(w);
  return (
    <figure className={`ride-ahead ride-ahead-${view}`} role="group" aria-labelledby={`${id}-h`} aria-describedby={`${id}-s`}>
      <p id={`${id}-h`} className="ride-ahead-heading">
        {AHEAD_HEADING[view]}
      </p>
      <p id={`${id}-s`} className="visually-hidden">
        {drawn.sentence}
        {riders ? ` ${riders}` : ""}
      </p>
      <svg className="ride-ahead-plot" viewBox={`0 0 ${W} ${H}`} aria-hidden="true" focusable="false">
        <defs>
          <pattern id={`${id}-steep`} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="5" height="5" fill={GRADE_BAND_FILL} />
            <line x1="0" y1="0" x2="0" y2="5" className="ride-ahead-hatch" />
          </pattern>
        </defs>
        {drawn.body(`${id}-steep`)}
        <Axis w={w} x={x} />
      </svg>
    </figure>
  );
}

type X = (m: number) => number;
type Y = (f: number) => number;

function Axis({ w, x }: { w: AheadWindow; x: X }) {
  const base = TOP + PLOT_H;
  const you = x(w.youM);
  return (
    <g className="ride-ahead-axis">
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
  body: (hatch: string) => React.ReactNode;
}

function draw(view: AheadView, route: Props["route"], w: AheadWindow, x: X, y: Y): Drawn | null {
  const profile = route.profile ?? null;
  if (view === "stress") {
    if (!route.stress_spans) return null;
    const bars = stressBars(route.stress_spans, w);
    if (!bars.length) return null;
    return {
      sentence: stressSentence(bars, w.youM),
      body: () =>
        bars.map((b) => {
          const left = x(b.fromM);
          const width = x(b.toM) - left;
          const top = y(barHeight(b.level));
          return (
            <g key={b.fromM}>
              <rect className="ride-ahead-bar" x={left} y={top} width={width} height={TOP + PLOT_H - top} fill={b.color} />
              {width >= b.label.length * 8 + 6 && (
                <text className="ride-ahead-level" x={left + width / 2} y={top + 15} textAnchor="middle" style={{ fill: b.ink }}>
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
    const steepest = shape.steep.length ? shape.steep.reduce((a, b) => (b.gradePct > a.gradePct ? b : a)) : null;
    return {
      sentence: elevationSentence(shape, w),
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
      body: () => (
        <>
          {steps.map((s) => (
            <rect key={s.fromM} x={x(s.fromM)} y={fy(s.riders)} width={Math.max(0.5, x(s.toM) - x(s.fromM))} height={TOP + PLOT_H - fy(s.riders)} fill={s.color} shapeRendering="crispEdges" />
          ))}
          {FLOW_GUIDES.slice(0, 2).map((g) => (
            <g key={g.at} className="ride-ahead-guide">
              <line x1={LEFT} x2={W - RIGHT} y1={fy(g.at)} y2={fy(g.at)} />
              <text x={W - RIGHT} y={fy(g.at) - 2} textAnchor="end">
                {g.at}
              </text>
            </g>
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
    body: () =>
      !marks.length ? (
        <text className="ride-ahead-none" x={W / 2} y={TOP + PLOT_H / 2 + 5} textAnchor="middle">
          {AHEAD_NO_CORKERS}
        </text>
      ) : marks.map((c, i) => {
        const at = x(c.m);
        const right = at > W * 0.6;
        const row = i % 2 === 0 ? TOP + 14 : TOP + 36;
        return (
          <g key={c.m} className="ride-ahead-corker">
            <line x1={at} x2={at} y1={TOP + PLOT_H} y2={row + 8} />
            <circle cx={at} cy={row} r={10} />
            <text className="ride-ahead-corker-n" x={at} y={row + 5} textAnchor="middle">
              {c.corkers}
            </text>
            {c.street && (
              <text className="ride-ahead-street" x={right ? at - 14 : at + 14} y={row + 5} textAnchor={right ? "end" : "start"}>
                {shortStreet(c.street)}
              </text>
            )}
          </g>
        );
      }),
  };
}
