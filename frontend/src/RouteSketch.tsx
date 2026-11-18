/**
 * A saved route's small picture in Load route and My routes (backlog 2026-11-12, Plan item 9, "Saved routes you can
 * tell apart at 50+"): the line's shape as the server keeps it (core.route_sketch), north up, the start a filled dot
 * and the end a ring. No base map, so nothing is fetched or stored per route (our default). Decorative: the row's
 * name and figures line say what it is, so a screen reader skips it.
 */
import type { SavedFigures } from "./lib/savedRoutes.ts";

/** The sketch's square, in the server's units (core.route_sketch.BOX), with room for the dots at its edge. */
const BOX = 100;
const PAD = 8;

export function RouteSketch({ figures }: { figures?: SavedFigures | null }) {
  const points = figures?.sketch;
  if (!points || points.length < 2) return <span className="route-sketch" aria-hidden="true" />;
  const [sx, sy] = points[0];
  const [ex, ey] = points[points.length - 1];
  return (
    <svg className="route-sketch" viewBox={`${-PAD} ${-PAD} ${BOX + 2 * PAD} ${BOX + 2 * PAD}`} aria-hidden="true" focusable="false" data-testid="route-sketch">
      <polyline className="route-sketch-line" points={points.map(([x, y]) => `${x},${y}`).join(" ")} />
      <circle className="route-sketch-end" cx={ex} cy={ey} r={7} />
      <circle className="route-sketch-start" cx={sx} cy={sy} r={7} />
    </svg>
  );
}
