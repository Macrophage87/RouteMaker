/**
 * Battery (the owner, 2026-11-01: battery audit): the follow camera eased the map at every fix, so a rider stood at a
 * light redrew the whole map once a second for nothing. A move is made only when it would show: the rider off the
 * camera's spot by a few screen pixels, the heading turned a few degrees, or a new zoom. The rider's marker moves as ever.
 */

/** A rider off the camera's spot by less than this many screen pixels is not worth a move. */
export const FOLLOW_STILL_PX = 3;
/** A bearing turned less than this many degrees is not worth a move. */
export const FOLLOW_STILL_DEG = 3;

export interface FollowMove {
  /** Where the rider is on screen now, and where the move would put them, in CSS pixels. */
  riderPx: readonly [number, number];
  targetPx: readonly [number, number];
  bearingNow: number;
  bearingWant: number;
  zoomNow: number;
  zoomWant: number;
  /** The first fix followed, or back on the rider after the screen was left alone (followReset): always moves. */
  first: boolean;
  /** The map mid-move, or left padded by the planner's framing: the camera is not where it rests, so it moves. */
  unsettled: boolean;
}

/** The smaller angle between two bearings, in degrees (359 and 1 are 2 apart). */
export function bearingGap(a: number, b: number): number {
  const d = (((a - b) % 360) + 360) % 360;
  return Math.min(d, 360 - d);
}

/** Whether the follow camera's move at this fix would show; when not, it is skipped. */
export function followMoveNeeded(move: FollowMove): boolean {
  if (move.first || move.unsettled) return true;
  if (Math.abs(move.zoomNow - move.zoomWant) > 1e-6) return true;
  if (bearingGap(move.bearingNow, move.bearingWant) >= FOLLOW_STILL_DEG) return true;
  const off = Math.hypot(move.riderPx[0] - move.targetPx[0], move.riderPx[1] - move.targetPx[1]);
  return off >= FOLLOW_STILL_PX;
}

/**
 * The map's drawing pixel ratio: in a ride or Roam at most 2, as a 3x screen draws more than twice the pixels of a
 * 2x one for a map read at a glance (the owner, 2026-11-01: battery audit). Off the bike, the screen's own.
 */
export function mapPixelRatio(devicePixelRatio: number, onBike: boolean): number {
  const screen = Number.isFinite(devicePixelRatio) && devicePixelRatio > 0 ? devicePixelRatio : 1;
  return onBike ? Math.min(screen, 2) : screen;
}
