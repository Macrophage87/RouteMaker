// The ride card's one arrow for a jog's turns (the owner, 2026-10-26: "When there's a series of manuvers in short
// succession, make an arrow that includes all of them").
import type { Cue, TurnMovement } from "./navigate.ts";

const TURN_DEG: Record<Exclude<TurnMovement, "uturn">, number> = { left: -90, right: 90, bear_left: -45, bear_right: 45 };

/** The stem before the first turn, a leg between turns, the last leg (before its arrowhead), and the head's sides. */
const STEM = 18;
const LEG = 16;
const LAST = 20;
const HEAD = 11;

/** The box the arrow fits in, in the card's 48 x 56 viewBox: its width, its height, its foot. */
const FIT_W = 36;
const FIT_H = 44;
const FOOT_Y = 50;
const MAX_SCALE = 1.4;

/**
 * The SVG path of a jog's arrow, for the card's 48 x 56 viewBox: up from the foot, a leg after each turn, the
 * arrowhead on the last. Null where the cue is no jog's (no turns after it) or a turn in it is a U-turn.
 */
export function jogArrowPath(cue: Pick<Cue, "movement" | "then">): string | null {
  if (!cue.then?.length || !cue.movement) return null;
  const moves = [cue.movement, ...cue.then.map((t) => t.movement)];
  if (moves.some((m) => m === "uturn")) return null;
  let x = 0;
  let y = 0;
  let heading = -90;
  const points: [number, number][] = [[x, y]];
  const go = (length: number) => {
    x += length * Math.cos((heading * Math.PI) / 180);
    y += length * Math.sin((heading * Math.PI) / 180);
    points.push([x, y]);
  };
  go(STEM);
  moves.forEach((m, i) => {
    heading += TURN_DEG[m as Exclude<TurnMovement, "uturn">];
    go(i === moves.length - 1 ? LAST : LEG);
  });
  const tip: [number, number] = [x, y];
  const head = [heading + 150, heading - 150].map((a): [number, number] => [x + HEAD * Math.cos((a * Math.PI) / 180), y + HEAD * Math.sin((a * Math.PI) / 180)]);
  const all = [...points, ...head];
  const xs = all.map((p) => p[0]);
  const ys = all.map((p) => p[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const k = Math.min(MAX_SCALE, FIT_W / (maxX - minX || 1), FIT_H / (maxY - minY || 1));
  const ox = 24 - ((minX + maxX) / 2) * k;
  const oy = FOOT_Y - maxY * k;
  const at = (p: [number, number]) => `${round(p[0] * k + ox)} ${round(p[1] * k + oy)}`;
  return `M${points.map(at).join(" L")} M${at(head[0])} L${at(tip)} L${at(head[1])}`;
}

function round(n: number): number {
  return Math.round(n * 10) / 10;
}
