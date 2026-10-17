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

/** The side button's name, for screen readers and as its tooltip. */
export const ROAD_CLOSED_NAME = "Road closed ahead";
/** Said on the press, while the way round is looked for. */
export const ROAD_CLOSED_FINDING = "Road closed. Finding a way round.";
/** Said where there is no place on the route or heading to tell which road is meant. */
export const ROAD_CLOSED_NO_PLACE = "Not sure which road is closed yet. Try again once moving.";
/** Said on taking the other line: the standard way through a marked closure, or back to its detour. */
export const ON_STANDARD_SAID = "On the standard route through the marked closure.";
export const ON_DETOUR_SAID = "On the detour.";

/** The closed stretch starts this far ahead of the rider (so the road they stand on behind it stays open)... */
export const CLOSED_FROM_M = 10;
/** ...and runs this far along the route (about 650 ft): past the next junction on most streets. */
export const CLOSED_LENGTH_M = 200;
/** Off the route, a stretch this long straight ahead along the rider's heading. */
export const CLOSED_HEADING_M = 150;
/** At most this many stretches a ride keeps (the API takes 10). */
export const CLOSED_MOST = 10;

const M_PER_DEG_LAT = 111_195;

/** A point `metres` from `p` on a compass heading (degrees from north). */
function ahead(p: LonLat, headingDeg: number, metres: number): LonLat {
  const rad = (headingDeg * Math.PI) / 180;
  const kx = M_PER_DEG_LAT * Math.cos((p[1] * Math.PI) / 180);
  return [p[0] + (Math.sin(rad) * metres) / kx, p[1] + (Math.cos(rad) * metres) / M_PER_DEG_LAT];
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
    const line: LonLat[] = [pointAt(model, from)];
    model.along.forEach((m, i) => {
      if (m > from && m < to) line.push(model.coordinates[i]);
    });
    line.push(pointAt(model, to));
    return { line, untilM: to };
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
 * within the off-route threshold of it. Null where it is not, or there is no other line.
 */
export function onOtherLine(other: Pick<RideModel, "coordinates" | "along"> | null, point: LonLat, accuracyM: number): number | null {
  if (!other) return null;
  const found = snap(other, point);
  if (!found || found.offM > offThreshold(accuracyM)) return null;
  return found.alongM;
}
