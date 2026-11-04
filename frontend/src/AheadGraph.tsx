/**
 * The ride's graphs of the road ahead (lib/aheadGraph.ts; Stephen 2026-11-03): a short card at the foot of the ride
 * screen, the next 2 miles by traffic stress, elevation, or on a Mass Ride rider flow or corkers. The graphs that are on
 * stack under one strip of turns and junction markers, on one distance axis labelled once at the foot ("Have each
 * graph share the same x axis, so it only needs to be labeled once"). Drawn in SVG; the picture is hidden from screen
 * readers, which hear one sentence a graph instead. Not a control: More's bubbles choose the graphs.
 *
 * Traffic stress is a ribbon under the turns, not a graph, so it fits beside elevation (Stephen 2026-11-04), each stretch
 * carrying its level, so colour is never the only cue, with the map's trail and bike lane rails on its edges; steep grades
 * are amber and hatched as on the route chart; turns are arrows, black, or orange on a triangle and red on a diamond
 * where the planner flagged the junction (the shapes of its junction markers); you are the triangle on the axis, and on
 * a shared ride each other rider a dot.
 */
import { Fragment, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { RouteResponse } from "./lib/api.ts";
import {
  AHEAD_GROUP,
  AHEAD_HEADING,
  AHEAD_NO_CORKERS,
  AHEAD_YOU,
  aheadWindow,
  axisTicks,
  corkerMarks,
  corkerSentence,
  elevationSentence,
  elevationShape,
  flowSentence,
  flowSteps,
  flowTop,
  narrowest,
  aheadNoRoom,
  graphsThatFit,
  PLOT_MIN,
  placeCorkerLabels,
  plotHeight,
  ridersSentence,
  spacedTicks,
  elevationTicks,
  flowTicks,
  stressBars,
  stressSentence,
  facilityStretches,
  facilitySentence,
  type FacilityStretch,
  type StressBar,
  spreadMarks,
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
import { ACCESS_MODE_CLASS } from "./lib/accessMode.ts";
import { units } from "./lib/units.ts";

/** The drawing's width, in viewBox units (about pixels on a phone), at the usual text size; larger text draws the same
 *  in a narrower box, so every word and mark grows with it (the v0.19.0 release review: the graph's text stayed 11 to
 *  15 px with Large text, accessibility mode or 200% text). */
const W = 320;
/** The height of the line naming graphs with no room, in CSS pixels (styles.css .ride-ahead-room). */
const NOTE_PX = 22;
/** How far short of the least room one graph is still drawn: Ride mode's hysteresis (RideMode AHEAD_HYSTERESIS_PX). */
const GRACE_PX = 6;
/** The most the drawing is enlarged for larger text. */
const ZOOM_MAX = 1.6;
/** The strip of turns at the top. */
const TURNS_H = 26;
/**
 * Traffic stress, a ribbon of the stress colours under the turns, each stretch carrying its level, so it sits beside
 * the other graphs (Stephen 2026-11-04: "You can't have both elevation and traffic stress. Maybe just make the traffic
 * stress a color ribbon with the turns on it").
 */
const RIBBON_H = 18;
/**
 * The trails and bike lanes along the ribbon's top and bottom edges, as the map's rails flank the route (Stephen
 * 2026-11-04: "put the bike lane or pbl markings on the top and bottom. Purple for trail"): each rail's width.
 */
const RAIL_H = 5;
/** A hair of panel between each rail and the ribbon, so a trail's purple stays apart from LTS 1's. */
const RAIL_GAP = 1.5;
/**
 * A half step's dash on the ribbon in the colour-blind-friendly palette, as the map's: a dash for 1.5 to 3.5, a
 * dash-dot for 4.5 (stressStyle.js HALF_STEP_TOP_DASH); its outline each dash a pixel longer at both ends.
 */
function halfDash(level: number | null): { dash: string; outline: string } {
  const dash = level === 4.5 ? [6, 3, 1.5, 3] : [6, 4];
  return { dash: dash.join(" "), outline: dash.map((d, i) => (i % 2 ? d - 2 : d + 2)).join(" ") };
}

/** The ribbon with its rails, top to bottom. */
const RIBBON_BLOCK = RAIL_H + RAIL_GAP + RIBBON_H + RAIL_GAP + RAIL_H;
/** The rails' dashes at this size, the map's look (stressStyle.js FACILITIES): trail solid, protected in posts, painted in dots. */
const RAIL_DASH: Record<FacilityStretch["facility"], string | undefined> = { path: undefined, protected: "5 3", lane: "2 3" };
/** Each graph: its name, then its plot. */
const LABEL_H = 14;
const GAP = 4;
const AXIS_H = 22;
/** Room on the left for the y axis's labels ("450 ft"). */
const LEFT = 46;
const RIGHT = 8;

interface Props {
  views: readonly AheadView[];
  route: Pick<RouteResponse, "profile" | "stress_spans">;
  /** The ride's cues, for the turns strip. */
  cues: readonly Pick<Cue, "kind" | "atM" | "movement" | "severity" | "joined" | "cross" | "source">[];
  /** You, metres along the route. */
  youM: number;
  lengthM: number;
  /** The other riders on the line, metres along (a shared ride). */
  ridersAlong?: readonly number[];
  /** The ride's Large text is on: the drawing grows with it. */
  large?: boolean;
  /** The most height the drawing may take, in CSS pixels, so the side buttons keep their room over it (RideMode); null for no limit. */
  maxPx?: number | null;
  /** Graphs on but not drawn, where there is no room for the line naming them either: the rider is told instead. */
  onNoRoom?: (views: readonly AheadView[]) => void;
}

/**
 * The least height one graph takes, in CSS pixels, at `widthPx` wide: its name, its plot at its shortest and the
 * distance axis, without the turns strip, and a pixel for rounding (RideMode: with less room than this, no graph is drawn and the rider is told).
 */
export function aheadLeastPx(widthPx: number, large: boolean): number {
  const width = Math.round(W / textZoom(large));
  return Math.ceil(((AXIS_H + LABEL_H + PLOT_MIN) * widthPx) / width) + 1;
}

/** How much larger than usual the drawing's text is: the page's root text size, the ride's Large text and accessibility mode. */
function textZoom(large: boolean): number {
  if (typeof document === "undefined") return 1;
  const root = document.documentElement;
  const rootPx = parseFloat(getComputedStyle(root).fontSize) || 16;
  const zoom = (rootPx / 16) * (large ? 1.25 : 1) * (root.classList.contains(ACCESS_MODE_CLASS) ? 1.2 : 1);
  return Math.min(ZOOM_MAX, Math.max(1, zoom));
}

/** Where a graph's plot sits in the drawing. */
interface Panel {
  top: number;
  h: number;
}

export function AheadGraph({ views, route, cues, youM, lengthM, ridersAlong = [], large = false, maxPx = null, onNoRoom }: Props) {
  const id = useId();
  const figureRef = useRef<HTMLElement>(null);
  // The drawing's width on screen, so a height in pixels is known in the drawing's units.
  const [widthPx, setWidthPx] = useState(0);
  useLayoutEffect(() => {
    const figure = figureRef.current;
    if (!figure) return;
    const measure = () => setWidthPx(Math.round(figure.clientWidth));
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(measure);
    watch.observe(figure);
    return () => watch.disconnect();
  }, []);
  // Read once per Large text change, not each render.
  const width = useMemo(() => Math.round(W / textZoom(large)), [large]);
  // Redrawn each 10 m, not each fix.
  const step = Math.floor(youM / 10) * 10;
  const ridersKey = ridersAlong.map((m) => Math.round(m / 10)).join(",");
  const w = useMemo(() => aheadWindow(step, lengthM, ridersAlong), [step, lengthM, ridersKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const x = (m: number) => LEFT + ((m - w.fromM) / (w.toM - w.fromM)) * (width - LEFT - RIGHT);
  const turns = useMemo(() => turnMarks(cues, w), [cues, w]);
  // Drawn at least 20 units apart, so two marks a block apart are one, not a blob.
  const drawnTurns = useMemo(() => spreadMarks(turns, (20 / (width - LEFT - RIGHT)) * (w.toM - w.fromM)), [turns, w, width]);
  // The plots as tall as the room allows (lib/aheadGraph.ts plotHeight): the room in pixels, in the drawing's units.
  const unit = widthPx > 0 ? width / widthPx : 1;
  const budget = maxPx !== null && widthPx > 0 ? maxPx * unit : Infinity;
  const panels = useMemo(() => {
    // Stress is the ribbon, not a graph (Stephen 2026-11-04): it sits under the turns strip, and the graphs share the
    // room under it. Its rails' room is kept whether or not one is in sight, so nothing under it jumps as one comes and goes.
    const ribbon = views.includes("stress") && route.stress_spans ? stressBars(route.stress_spans, w) : [];
    const rails = ribbon.length && route.stress_spans ? facilityStretches(route.stress_spans, w) : [];
    const ribbonH = ribbon.length ? RIBBON_BLOCK + GAP : 0;
    const graphs = views.filter((view) => view !== "stress");
    const fit = (count: number, room: number, strip: number) => graphsThatFit(count, room, strip + AXIS_H - GAP, LABEL_H + GAP);
    // Where the room holds fewer graphs than are on, the first ones are drawn (lib/aheadGraph.ts graphsThatFit), with a
    // line under them naming the rest, which take its height; every one is still said. Counted from the graphs on
    // first, so the usual case draws each once.
    let order: readonly AheadView[] = graphs;
    let turnsH = TURNS_H;
    let count = fit(graphs.length, budget, turnsH + ribbonH);
    if (count < graphs.length) {
      order = graphs.filter((view) => draw(view, route, w, x, { top: 0, h: PLOT_MIN }, width) !== null);
      count = fit(order.length, budget, turnsH + ribbonH);
      if (count < order.length) count = fit(order.length, budget - NOTE_PX * unit, turnsH + ribbonH);
    }
    // Room for no graph under the turns strip: one graph without it (the turns are in the sentence), the rest named
    // in a line under it, or where there is no room for that either, told (onNoRoom).
    let note = count < order.length;
    if (count === 0 && order.length) {
      if (fit(1, budget - (order.length > 1 ? NOTE_PX * unit : 0), ribbonH) === 1) {
        turnsH = 0;
        count = 1;
      } else if (!ribbon.length && fit(1, budget + GRACE_PX * unit, 0) === 1) {
        // Ride mode found room for one (aheadLeastPx, give or take its few px of hysteresis): one, without the line.
        // Less than that (a note in the panel for now): none, until it goes. With the ribbon on, the ribbon alone is
        // drawn instead (below), within the room.
        turnsH = 0;
        count = 1;
        note = false;
      }
    }
    // No graph fits beside the ribbon: the ribbon alone, with the turns where they fit, and the graphs not drawn named
    // under it where that line fits too, else told (onNoRoom). With no room for even the ribbon, it is said, not drawn.
    let ribbonDrawn = ribbon.length > 0;
    if (ribbonDrawn && count === 0) {
      const alone = (turns: number) => turns + ribbonH + AXIS_H;
      const line = order.length ? NOTE_PX * unit : 0;
      const pick = (
        [
          [TURNS_H, true],
          [0, true],
          [TURNS_H, false],
          [0, false],
        ] as const
      ).find(([turns, withLine]) => (withLine || line > 0) && budget >= alone(turns) + (withLine ? line : 0));
      if (pick) {
        turnsH = pick[0];
        note = order.length > 0 && pick[1];
      } else ribbonDrawn = false;
    }
    const shown = order.slice(0, count);
    const strip = turnsH + (ribbonDrawn ? ribbonH : 0);
    const fixed = strip + AXIS_H + shown.length * (LABEL_H + GAP) - GAP + (note ? NOTE_PX * unit : 0);
    const h = plotHeight(shown.length, budget, fixed);
    const drawn: { view: AheadView; panel: Panel; drawn: Drawn }[] = [];
    let at = strip;
    for (const view of shown) {
      const panel = { top: at + LABEL_H, h };
      const one = draw(view, route, w, x, panel, width);
      if (!one) continue;
      drawn.push({ view, panel, drawn: one });
      at = panel.top + panel.h + GAP;
    }
    const unseen = order.slice(count);
    const unseenSaid = unseen.map((view) => `${AHEAD_HEADING[view]}: ${draw(view, route, w, x, { top: 0, h: PLOT_MIN }, width)!.sentence}`);
    const any = drawn.length > 0 || ribbonDrawn;
    const ribbonSaid = ribbon.length ? [`${AHEAD_HEADING.stress}: ${stressSentence(ribbon, w.youM)}`, facilitySentence(rails, w.youM)].filter(Boolean).join(" ") : "";
    return {
      drawn,
      unseen,
      unseenSaid,
      turnsH,
      strip,
      ribbon: ribbonDrawn ? ribbon : [],
      rails,
      ribbonSaid,
      any,
      note: note && unseen.length > 0 && any,
      // With the ribbon alone, the axis goes right under it (its GAP is in ribbonH).
      base: drawn.length ? at - GAP : strip,
    };
  // The units in use too: switched during a ride (lib/units.ts switchUnitsInRide), the heights and sentences follow.
  }, [views, route, w, width, budget, unit, units()]); // eslint-disable-line react-hooks/exhaustive-deps
  const { base } = panels;
  const untold = !panels.note && panels.any ? panels.unseen.join(",") : "";
  useEffect(() => {
    if (untold) onNoRoom?.(untold.split(",") as AheadView[]);
  }, [untold]); // eslint-disable-line react-hooks/exhaustive-deps
  const H = base + AXIS_H;
  if (!panels.any && !panels.unseenSaid.length && !panels.ribbonSaid) return <figure ref={figureRef} className="ride-ahead" hidden />;
  const riders = ridersSentence(w);
  const said = [
    turnsSentence(turns, w.youM),
    panels.ribbonSaid,
    ...panels.drawn.map((p) => `${AHEAD_HEADING[p.view]}: ${p.drawn.sentence}`),
    ...panels.unseenSaid,
    riders,
  ].filter(Boolean).join(" ");
  return (
    // None drawn (no room for now, or on this screen): the sentence alone, visually hidden, so a screen reader still
    // hears the road ahead (the review of #928).
    <figure ref={figureRef} className={panels.any ? "ride-ahead" : "ride-ahead ride-ahead-unseen"} role="group" aria-label={AHEAD_GROUP}>
      <p className="visually-hidden">{said}</p>
      {panels.any && (
        <svg className="ride-ahead-plot" viewBox={`0 0 ${width} ${H}`} aria-hidden="true" focusable="false">
          <defs>
            <pattern id={`${id}-climb`} width="4" height="4" patternUnits="userSpaceOnUse">
              <rect width="4" height="4" fill={GRADE_BAND_FILL} />
              <circle cx="2" cy="2" r="0.8" className="ride-ahead-dot" />
            </pattern>
            <pattern id={`${id}-steep`} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="5" height="5" fill={GRADE_BAND_FILL} />
              <line x1="0" y1="0" x2="0" y2="5" className="ride-ahead-hatch" />
            </pattern>
          </defs>
          {panels.turnsH > 0 && <Turns marks={drawnTurns} x={x} />}
          {panels.ribbon.length > 0 && <Ribbon bars={panels.ribbon} rails={panels.rails} x={x} top={panels.turnsH} turns={panels.turnsH > 0 ? drawnTurns : []} />}
          {panels.drawn.map(({ view, panel, drawn }) => (
            <Fragment key={view}>
              <text className="ride-ahead-name" x={LEFT} y={panel.top - 3}>
                {AHEAD_HEADING[view]}
              </text>
              {drawn.body(`${id}-steep`, `${id}-climb`)}
              <YAxis ticks={drawn.yTicks} panel={panel} />
            </Fragment>
          ))}
          <Axis w={w} x={x} base={base} top={panels.strip} width={width} />
        </svg>
      )}
      {/* The graphs on but not drawn, for want of room: named, as the sentence above already says each. */}
      {panels.note && (
        <p className="ride-ahead-room" aria-hidden="true">
          {aheadNoRoom(panels.unseen)}
        </p>
      )}
    </figure>
  );
}

/**
 * A turn's arrow, drawn about a point: a shaft and a solid head; left ones are right ones mirrored (Stephen 2026-11-03:
 * "clean up the arrows").
 */
const ARROWS: Record<NonNullable<TurnMark["movement"]>, { shaft: string; head: string; flip: boolean }> = {
  right: { shaft: "M-5 9V1a2 2 0 0 1 2-2H1", head: "M0-6.5L7.5-1L0 4.5Z", flip: false },
  left: { shaft: "M-5 9V1a2 2 0 0 1 2-2H1", head: "M0-6.5L7.5-1L0 4.5Z", flip: true },
  bear_right: { shaft: "M-4 9V3.5L2.5-3", head: "M6.5-7L5.5 2L-2.5-6Z", flip: false },
  bear_left: { shaft: "M-4 9V3.5L2.5-3", head: "M6.5-7L5.5 2L-2.5-6Z", flip: true },
  uturn: { shaft: "M4 9V-2a4 4 0 0 0-8 0V2", head: "M-9 1L-4 8L1 1Z", flip: false },
};

/**
 * The strip of turns and junction markers, over the graphs on the same scale. A turn is a black arrow, or orange or red
 * where the planner flagged its junction (Stephen 2026-11-03: "make those arrows that color alone"), each in a dark edge
 * so it holds 3:1 on the panel; a flagged junction that is not a turn is the planner's own marker, an orange triangle
 * or a red diamond, and an Avoid stretch a magenta square.
 */
function Turns({ marks, x }: { marks: readonly TurnMark[]; x: X }) {
  const cy = TURNS_H / 2;
  return (
    <g className="ride-ahead-turns">
      {marks.map((mark, i) => {
        const cx = x(mark.m);
        const colour = mark.severity === "orange" || mark.severity === "red" ? SEVERITY_COLOURS[mark.severity] : null;
        if (mark.movement) {
          const arrow = ARROWS[mark.movement];
          return (
            <g key={i} transform={`translate(${cx} ${cy}) scale(${arrow.flip ? -1 : 1} 1)`} className={colour ? `ride-ahead-arrow ride-ahead-arrow-${mark.severity}` : "ride-ahead-arrow"}>
              {colour && <path d={arrow.shaft} className="ride-ahead-arrow-edge" stroke={colour.stroke} />}
              {colour && <path d={arrow.head} className="ride-ahead-arrow-edge" stroke={colour.stroke} fill={colour.stroke} />}
              <path d={arrow.shaft} className="ride-ahead-arrow-shaft" style={colour ? { stroke: colour.fill } : undefined} />
              <path d={arrow.head} className="ride-ahead-arrow-head" style={colour ? { fill: colour.fill } : undefined} />
            </g>
          );
        }
        if (mark.severity === "orange" || mark.severity === "red") {
          const d = mark.severity === "orange" ? `M${cx} ${cy - 9}l9 16h-18z` : `M${cx} ${cy - 9}l9 9-9 9-9-9z`;
          return <path key={i} d={d} fill={colour?.fill} stroke={colour?.stroke} strokeWidth={1.5} />;
        }
        return <rect key={i} x={cx - 7} y={cy - 7} width={14} height={14} fill={ROUTE_AVOID_MAGENTA} stroke="#1c1917" strokeWidth={1.5} />;
      })}
    </g>
  );
}

/**
 * Traffic stress as a ribbon: each stretch in its stress colour, its level on it where it fits (so colour is never the
 * only cue), "LTS" in the gutter, and a line through it at each turn above, tying the turn to the stretch it leads onto.
 * Along its top and bottom edges, each trail or bike lane as the map draws its rails beside the route (trail solid
 * purple, protected lane in posts, painted in dots); the sentence says them too.
 */
function Ribbon({ bars, rails, x, top, turns }: { bars: readonly StressBar[]; rails: readonly FacilityStretch[]; x: X; top: number; turns: readonly TurnMark[] }) {
  const band = top + RAIL_H + RAIL_GAP;
  const railYs = [top + RAIL_H / 2, band + RIBBON_H + RAIL_GAP + RAIL_H / 2];
  return (
    <g className="ride-ahead-ribbon">
      <text className="ride-ahead-ribbon-name" x={LEFT - 6} y={band + RIBBON_H / 2 + 5} textAnchor="end">
        LTS
      </text>
      {bars.map((b) => {
        const left = x(b.fromM);
        const width = x(b.toM) - left;
        return (
          <g key={b.fromM}>
            <rect className="ride-ahead-bar" x={left} y={band} width={width} height={RIBBON_H} fill={b.color} />
            {b.halfDash && (
              // A half step in the colour-blind-friendly palette: the next level's dash along its foot, as on the map.
              <g className="ride-ahead-half-dash">
                {b.halfOutline && (
                  // The outline a pixel round each dash, its ends too (as the map's scaledDash), so 4.5's dash keeps
                  // its rim on LTS 4's red.
                  <line x1={left} x2={left + width} y1={band + RIBBON_H - 3} y2={band + RIBBON_H - 3} stroke={b.halfOutline} strokeWidth={5.5} strokeDasharray={halfDash(b.level).outline} strokeDashoffset={1} />
                )}
                <line x1={left} x2={left + width} y1={band + RIBBON_H - 3} y2={band + RIBBON_H - 3} stroke={b.halfDash} strokeWidth={3.5} strokeDasharray={halfDash(b.level).dash} />
              </g>
            )}
            {width >= b.label.length * 8 + 6 && (
              // Lifted a little over a half step's dash, so the dash runs under the number.
              <text className="ride-ahead-level" x={left + width / 2} y={band + RIBBON_H / 2 + (b.halfDash ? 3 : 5)} textAnchor="middle" style={{ fill: b.ink }}>
                {b.label}
              </text>
            )}
          </g>
        );
      })}
      {rails.map((rail) =>
        railYs.map((y) => (
          <g key={`${rail.fromM}-${y}`} className="ride-ahead-rail">
            {/* An edge, so the dark trail purple still reads on the dark panel (styles.css). */}
            <line className="ride-ahead-rail-edge" x1={x(rail.fromM)} x2={x(rail.toM)} y1={y} y2={y} strokeWidth={RAIL_H + 1.5} strokeDasharray={RAIL_DASH[rail.facility]} />
            <line x1={x(rail.fromM)} x2={x(rail.toM)} y1={y} y2={y} stroke={rail.color} strokeWidth={RAIL_H} strokeDasharray={RAIL_DASH[rail.facility]} />
          </g>
        )),
      )}
      {turns.filter((mark) => mark.movement).map((mark, i) => (
        <line key={i} className="ride-ahead-ribbon-turn" x1={x(mark.m)} x2={x(mark.m)} y1={top} y2={top + RIBBON_BLOCK} />
      ))}
    </g>
  );
}

/** The y axis: its line and each label beside its tick, right-aligned in the gutter. */
function YAxis({ ticks, panel }: { ticks: readonly YTick[]; panel: Panel }) {
  if (!ticks.length) return null;
  return (
    <g className="ride-ahead-axis ride-ahead-y">
      <line x1={LEFT} x2={LEFT} y1={panel.top} y2={panel.top + panel.h} />
      {spacedTicks(ticks, 13).map((tick) => (
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
function Axis({ w, x, base, top, width: W }: { w: AheadWindow; x: X; base: number; top: number; width: number }) {
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
  body: (hatch: string, dots: string) => React.ReactNode;
}

function draw(view: AheadView, route: Props["route"], w: AheadWindow, x: X, panel: Panel, W: number): Drawn | null {
  const profile = route.profile ?? null;
  const TOP = panel.top;
  const PLOT_H = panel.h;
  const y = (f: number) => TOP + PLOT_H * (1 - f);
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
      body: (hatch, dots) => (
        <>
          <path className="ride-ahead-ground" d={under(w.fromM, w.toM)} />
          {shape.steep.map((s) => (
            <path key={s.fromM} d={under(s.fromM, s.toM)} fill={`url(#${s.band === 2 ? hatch : dots})`} className={`ride-ahead-steep-${s.band}`} />
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
              <text x={Math.min(W - 20, Math.max(LEFT + 12, x((low.fromM + low.toM) / 2)))} y={TOP + 10} textAnchor="middle">
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
      ) : (() => {
        // The markers in a row at the top; each street's short name beside its stem on the first row under them with
        // room (placeCorkerLabels), as many rows as the plot holds.
        const rows = Math.max(0, Math.min(2, Math.floor((PLOT_H - 22) / 17)));
        const placed = placeCorkerLabels(
          marks.map((c) => ({ at: x(c.m), street: c.street, leftOf: x(c.m) > W * 0.6 })),
          rows,
          8.4,
        );
        const mark = TOP + 10;
        // The stems and markers first, then the names over them.
        return (
          <>
            {marks.map((c) => {
              const at = x(c.m);
              return (
                <g key={c.m} className="ride-ahead-corker">
                  <line x1={at} x2={at} y1={TOP + PLOT_H} y2={mark + 8} />
                  <circle cx={at} cy={mark} r={8} />
                  <text className="ride-ahead-corker-n" x={at} y={mark + 4.5} textAnchor="middle">
                    {c.corkers}
                  </text>
                </g>
              );
            })}
            {marks.map((c, i) => {
              const at = x(c.m);
              const { row, text } = placed[i];
              if (!text || row === null) return null;
              const left = at > W * 0.6;
              return (
                <text key={c.m} className="ride-ahead-street" x={left ? at - 5 : at + 5} y={mark + 23 + row * 17} textAnchor={left ? "end" : "start"}>
                  {text}
                </text>
              );
            })}
          </>
        );
      })(),
  };
}
