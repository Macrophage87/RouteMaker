/**
 * Closures on the move (v0.8.2; the owner, 2026-10-17).
 *
 * The standard way and the detour: "There are several closures marked that aren't actually closed. We should have
 * both the standard route and the detour in that case. If you take the standard route, just keep going, if you move
 * to the detour take that." A route that goes round a closure carries the standard way through it
 * (`closure_through`); Ride draws it beside the route, and a rider who leaves one for the other is followed on the one
 * they took, with no re-plan and no "off route" (`onOtherLine`).
 *
 * Road closed: "there were times where the road ahead was closed but it wasn't marked. There should be a button for
 * that (included with the side buttons) that can be quickly pressed in that event and assist in navigation, without
 * trying to put people back onto the closed road." One press marks the road ahead closed for this ride
 * (`closedAhead`): every re-plan of the ride leaves it out (the API's `blocked_lines`), and the way back to the planned
 * route joins it past the closed stretch, never on it. Nothing is reported anywhere.
 *
 * Pure, so it is tested without a map or a DOM.
 */
import type { LonLat } from "./geo.ts";
import { offThreshold, pointAt, snap, type RideModel } from "./navigate.ts";

/** The ride top row's button's name, for screen readers and as its tooltip. */
export const ROAD_CLOSED_NAME = "Road closed ahead";
/** Its shown words in the ride's top row (the name keeps "ahead"; WCAG 2.5.3, the words start the name). */
export const ROAD_CLOSED_TEXT = "Road closed";
/** Said on the press, while the way round is looked for. */
export const ROAD_CLOSED_FINDING = "Road closed. Finding a way round.";
/** Said where there is no place on the route or heading to tell which road is meant. */
export const ROAD_CLOSED_NO_PLACE = "Not sure which road is closed yet. Try again once moving.";
/** Said on taking the other line: the standard way through a marked closure, or back to its detour. */
export const ON_STANDARD_SAID = "On the standard route through the marked closure.";
export const ON_DETOUR_SAID = "On the detour.";

/**
 * The closed stretch starts this far ahead of the rider: the router leaves out every road the strip touches, so a
 * rider stopped just before a junction keeps its cross streets as a way round...
 */
export const CLOSED_FROM_M = 30;
/** ...and runs this far along the route (about 500 ft): to the next junction on most streets. */
export const CLOSED_LENGTH_M = 150;
/** Off the route, a stretch this long straight ahead along the rider's heading. */
export const CLOSED_HEADING_M = 150;
/** At most this many stretches a ride keeps, so they fit the router's limit beside the closures (the API takes 10). */
export const CLOSED_MOST = 6;

const M_PER_DEG_LAT = 111_195;

/** A point `metres` from `p` on a compass heading (degrees from north). */
function ahead(p: LonLat, headingDeg: number, metres: number): LonLat {
  const rad = (headingDeg * Math.PI) / 180;
  const kx = M_PER_DEG_LAT * Math.cos((p[1] * Math.PI) / 180);
  return [p[0] + (Math.sin(rad) * metres) / kx, p[1] + (Math.cos(rad) * metres) / M_PER_DEG_LAT];
}

/** Metres from `p` to the straight line through `a` and `b`. */
function offChord(p: LonLat, a: LonLat, b: LonLat): number {
  const kx = M_PER_DEG_LAT * Math.cos((p[1] * Math.PI) / 180);
  const [ax, ay, bx, by, px, py] = [a[0] * kx, a[1] * M_PER_DEG_LAT, b[0] * kx, b[1] * M_PER_DEG_LAT, p[0] * kx, p[1] * M_PER_DEG_LAT];
  const len = Math.hypot(bx - ax, by - ay);
  if (len === 0) return Math.hypot(px - ax, py - ay);
  return Math.abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / len;
}

export interface ClosedStretch {
  /** The line to leave out, [lon, lat] pairs. */
  line: LonLat[];
  /** Where it ends along the route (metres), or null where it was taken from the heading. */
  untilM: number | null;
}

/**
 * The road ahead, as one press marks it closed: on the route, from CLOSED_FROM_M ahead of the rider to
 * CLOSED_LENGTH_M further along it (through the next turn, where there is one); off it, straight ahead along the
 * heading. Null where neither can be told (no place on the route and no heading), or at the very end.
 */
export function closedAhead(
  model: Pick<RideModel, "coordinates" | "along" | "lengthM">,
  progressM: number | null,
  off: boolean,
  here: LonLat | null,
  headingDeg: number | null,
): ClosedStretch | null {
  if (!off && progressM !== null) {
    const from = progressM + CLOSED_FROM_M;
    const to = Math.min(from + CLOSED_LENGTH_M, model.lengthM);
    if (to - from < 20) return null;
    // Its ends and, where it bends, the vertex farthest off the straight between them (the turn): the server keeps
    // only a few points of a strip, and a curvy trail would have too many to send.
    const start = pointAt(model, from);
    const end = pointAt(model, to);
    let bend: LonLat | null = null;
    let most = 5;
    model.along.forEach((m, i) => {
      if (m <= from || m >= to) return;
      const off = offChord(model.coordinates[i], start, end);
      if (off > most) {
        most = off;
        bend = model.coordinates[i];
      }
    });
    return { line: bend ? [start, bend, end] : [start, end], untilM: to };
  }
  if (here && headingDeg !== null && Number.isFinite(headingDeg)) {
    return { line: [ahead(here, headingDeg, CLOSED_FROM_M), ahead(here, headingDeg, CLOSED_FROM_M + CLOSED_HEADING_M)], untilM: null };
  }
  return null;
}

/** The ride's stretches with one more, the oldest dropped past CLOSED_MOST. */
export function withClosed(lines: readonly LonLat[][], line: LonLat[]): LonLat[][] {
  return [...lines, line].slice(-CLOSED_MOST);
}

/**
 * Where on the other line (the standard way, or the detour while on the standard way) a fix is, when it is on it:
 * within the off-route threshold of it. Null where it is not, or there is no other line. Where it passes the same
 * place twice (a loop, an out-and-back), the pass nearest `nearM` along is taken: the rider's progress on the route
 * left, which the two lines share up to where they part.
 */
export function onOtherLine(other: Pick<RideModel, "coordinates" | "along"> | null, point: LonLat, accuracyM: number, nearM = -Infinity): number | null {
  if (!other) return null;
  const found = snap(other, point, -Infinity, Infinity, 15, nearM);
  if (!found || found.offM > offThreshold(accuracyM)) return null;
  return found.alongM;
}
