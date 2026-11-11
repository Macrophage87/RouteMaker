/**
 * The picture beside each cue of the phone cue images (the owner, 2026-11-10: "some people perfer to just navigate by
 * a static image ... Basically show the arrows"), as plain geometry in a 100 by 100 box so it is tested without a
 * canvas and drawn the same way by the browser (app/lockScreenRender.ts) and the connector (src/core/cue_cards.py,
 * which follows this file: keep the two alike).
 *
 * A turn is an arrow up from the foot with a leg after each turn, a jog's later turns in the same arrow as the ride
 * card draws them (jogArrow.ts), a U-turn as a hook to the left. A turn onto a path across a road, and a short path
 * straight across one, are drawn over the road's two edges, as Ride's crossArrow. Start is a ring with a dot, Finish
 * a chequered flag, a stop a disc with its number, a caution a warning triangle, a walk a dashed arrow.
 */
import type { TurnMovement } from "./navigate.ts";

export type CueArrow =
  | { kind: "turn"; moves: readonly TurnMovement[]; across: boolean }
  | { kind: "cross" }
  | { kind: "start" }
  | { kind: "finish" }
  | { kind: "stop"; number: number | null }
  | { kind: "caution" }
  | { kind: "walk" }
  | { kind: "note" };

type Point = [number, number];

export interface ArrowShape {
  /** Thick round-capped lines (ARROW_STROKE wide). */
  strokes: Point[][];
  /** Thin lines (EDGE_STROKE wide): a road's edges, a flag's outline. */
  thin: Point[][];
  /** Filled polygons: arrowheads, a flag's squares. */
  fills: Point[][];
  /** Filled discs, and rings (`ring` is the ring's width). */
  discs: { x: number; y: number; r: number; ring?: number }[];
  /** A word in the paper's colour on a disc (a stop's number), centred, `px` high in box units. */
  label?: { x: number; y: number; text: string; px: number };
}

export const ARROW_STROKE = 11;
export const EDGE_STROKE = 4;

const TURN_DEG: Record<Exclude<TurnMovement, "uturn">, number> = { left: -90, right: 90, bear_left: -45, bear_right: 45 };
const STEM = 40;
const LEG = 28;
const LAST = 30;
const UTURN_R = 16;
const HEAD_LEN = 22;
const HEAD_HALF = 20;
const FIT = { left: 8, right: 92, top: 6, bottom: 94 } as const;
const MAX_SCALE = 1.6;

const round = (n: number) => Math.round(n * 10) / 10;

/** The arrow's points from (0, 0) heading up, and its last heading in degrees (0 east, 90 south). */
function walkPath(moves: readonly TurnMovement[], stem: number): { points: Point[]; heading: number } {
  let x = 0;
  let y = 0;
  let heading = -90;
  const points: Point[] = [[x, y]];
  const go = (length: number) => {
    x += length * Math.cos((heading * Math.PI) / 180);
    y += length * Math.sin((heading * Math.PI) / 180);
    points.push([x, y]);
  };
  go(stem);
  moves.forEach((m, i) => {
    if (m === "uturn") {
      // A hook to the left: a half circle, then back down.
      const cx = x + UTURN_R * Math.cos(((heading - 90) * Math.PI) / 180);
      const cy = y + UTURN_R * Math.sin(((heading - 90) * Math.PI) / 180);
      const from = heading + 90;
      for (let k = 1; k <= 8; k += 1) {
        const a = ((from - (180 * k) / 8) * Math.PI) / 180;
        points.push([cx + UTURN_R * Math.cos(a), cy + UTURN_R * Math.sin(a)]);
      }
      [x, y] = points[points.length - 1];
      heading -= 180;
      go(i === moves.length - 1 ? STEM * 0.5 : LEG);
      return;
    }
    heading += TURN_DEG[m];
    go(i === moves.length - 1 ? LAST : LEG);
  });
  return { points, heading };
}

function head(tip: Point, heading: number): Point[] {
  const a = (heading * Math.PI) / 180;
  const [dx, dy] = [Math.cos(a), Math.sin(a)];
  const base: Point = [tip[0] - dx * HEAD_LEN, tip[1] - dy * HEAD_LEN];
  return [tip, [base[0] - dy * HEAD_HALF, base[1] + dx * HEAD_HALF], [base[0] + dy * HEAD_HALF, base[1] - dx * HEAD_HALF]];
}

/** An arrow along `moves` (none: straight on), fitted in the box; `edges`, a road's two edges across the stem. */
function arrow(moves: readonly TurnMovement[], edges: boolean, dashed = false): ArrowShape {
  // Across a road first: a longer stem, the road's edges on its lower part, clear of the turn.
  const stem = moves.length ? STEM + (edges ? 22 : 0) : STEM + LAST + 10;
  const { points, heading } = walkPath(moves, stem);
  // The line stops at the head's base, so the head's point is sharp.
  const tip = points[points.length - 1];
  const fill = head(tip, heading);
  const a = (heading * Math.PI) / 180;
  const shaft = [...points.slice(0, -1), [tip[0] - Math.cos(a) * (HEAD_LEN - 2), tip[1] - Math.sin(a) * (HEAD_LEN - 2)] as Point];
  const all = [...points, ...fill];
  const xs = all.map((p) => p[0]);
  const ys = all.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const k = Math.min(MAX_SCALE, (FIT.right - FIT.left) / (maxX - minX || 1), (FIT.bottom - FIT.top) / (maxY - minY || 1));
  const ox = 50 - ((minX + maxX) / 2) * k;
  const oy = FIT.bottom - maxY * k;
  const at = (p: Point): Point => [round(p[0] * k + ox), round(p[1] * k + oy)];
  const strokes = dashed ? dashes(shaft.map(at)) : [shaft.map(at)];
  const shape: ArrowShape = { strokes, thin: [], fills: [fill.map(at)], discs: [] };
  if (edges) {
    // The road's two edges across the stem's upper part, the width of the box.
    const y1 = round(oy - stem * 0.2 * k);
    const y2 = round(oy - stem * 0.6 * k);
    shape.thin = [
      [[2, y1], [98, y1]],
      [[2, y2], [98, y2]],
    ];
  }
  return shape;
}

/** A line cut into dashes, for the walk. */
function dashes(line: Point[]): Point[][] {
  const out: Point[][] = [];
  const DASH = 12;
  const GAP = 9;
  for (let i = 1; i < line.length; i += 1) {
    const [a, b] = [line[i - 1], line[i]];
    const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
    for (let s = 0; s < length; s += DASH + GAP) {
      const e = Math.min(length, s + DASH);
      const p = (t: number): Point => [round(a[0] + ((b[0] - a[0]) * t) / length), round(a[1] + ((b[1] - a[1]) * t) / length)];
      out.push([p(s), p(e)]);
    }
  }
  return out;
}

/** The picture for a cue. */
export function arrowShape(cue: CueArrow): ArrowShape {
  switch (cue.kind) {
    case "turn":
      return arrow(cue.moves, cue.across);
    case "cross":
      return arrow([], true);
    case "walk":
      return arrow([], false, true);
    case "start":
      return { strokes: [], thin: [], fills: [], discs: [{ x: 50, y: 50, r: 36, ring: ARROW_STROKE }, { x: 50, y: 50, r: 14 }] };
    case "finish": {
      // A pole and a flag of 4 by 3 squares, every other one filled.
      const [left, top, size] = [32, 12, 13];
      const fills: Point[][] = [];
      for (let row = 0; row < 3; row += 1) {
        for (let col = 0; col < 4; col += 1) {
          if ((row + col) % 2) continue;
          const [x, y] = [left + col * size, top + row * size];
          fills.push([[x, y], [x + size, y], [x + size, y + size], [x, y + size]]);
        }
      }
      const [right, bottom] = [left + 4 * size, top + 3 * size];
      return {
        strokes: [[[left - 4, top - 2], [left - 4, 94]]],
        thin: [[[left, top], [right, top], [right, bottom], [left, bottom], [left, top]]],
        fills,
        discs: [],
      };
    }
    case "stop":
      return { strokes: [], thin: [], fills: [], discs: [{ x: 50, y: 50, r: 42 }], ...(cue.number != null ? { label: { x: 50, y: 50, text: String(cue.number), px: 46 } } : {}) };
    case "caution":
      return {
        strokes: [[[50, 8], [94, 88], [6, 88], [50, 8]], [[50, 38], [50, 62]]],
        thin: [],
        fills: [],
        discs: [{ x: 50, y: 75, r: 6 }],
      };
    case "note":
      return { strokes: [[[50, 46], [50, 72]]], thin: [], fills: [], discs: [{ x: 50, y: 50, r: 40, ring: ARROW_STROKE * 0.8 }, { x: 50, y: 32, r: 6 }] };
  }
}
