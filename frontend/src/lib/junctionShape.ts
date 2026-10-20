/**
 * The ride card's picture of an unusual junction (the owner, 2026-10-20: "if there's a left turn on a service
 * road show the non-picked intersections dashed. Likewise with 5 way intersections"): the way in from the
 * bottom and the way the route takes solid, with its arrowhead, and every other way dashed. The API says which
 * junctions are unusual (`describe.junction_shape`); any other turn keeps its plain arrow. A picture only: the
 * card's words, the voice and the screen-reader text say the turn as they did.
 */

/** The ways at a junction, in degrees from straight ahead as the rider arrives, clockwise positive. */
export interface JunctionShape {
  out: number;
  others: number[];
}

/** The card's arrow box (RideMode CueShape): 48 by 56, the junction a little below the middle. */
const CENTRE = { x: 24, y: 30 };
const BRANCH = 20;
const HEAD = 9;
const HEAD_DEG = 40;

function round(n: number): number {
  return Math.round(n * 10) / 10;
}

/** The point `length` from `from` at `deg` clockwise from straight up. */
function toward(from: { x: number; y: number }, deg: number, length: number): { x: number; y: number } {
  const r = (deg * Math.PI) / 180;
  return { x: round(from.x + length * Math.sin(r)), y: round(from.y - length * Math.cos(r)) };
}

/** SVG paths for the diagram: `route` (in, then the way taken, with its head) solid; `others` dashed. */
export function junctionPaths(shape: JunctionShape): { route: string; others: string[] } {
  const end = toward(CENTRE, shape.out, BRANCH);
  // The head's two strokes point back from the tip, either side of the way taken.
  const back = shape.out + 180;
  const a = toward(end, back - HEAD_DEG, HEAD);
  const b = toward(end, back + HEAD_DEG, HEAD);
  const route = `M24 52 L${CENTRE.x} ${CENTRE.y} L${end.x} ${end.y} M${a.x} ${a.y} L${end.x} ${end.y} L${b.x} ${b.y}`;
  const others = shape.others.map((deg) => {
    const tip = toward(CENTRE, deg, BRANCH);
    return `M${CENTRE.x} ${CENTRE.y} L${tip.x} ${tip.y}`;
  });
  return { route, others };
}
