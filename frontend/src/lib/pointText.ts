/**
 * What the page says about the plan's points: the map markers' labels, the
 * announcements a screen reader hears when a point is added, set, removed or
 * the order reversed, and the hints under the points list. In a loop the
 * rider chose (OWNER-DECISIONS 374) the first point is the start and finish,
 * every later one a stop, and there is no end. Mass Ride has no loop, so its
 * hints never mention the toggle.
 */
import { LOOP_LABEL, canReverse, loopStops } from "./loop.ts";
import type { LonLat } from "./geo.ts";
import type { PresetId } from "./presets.ts";
import { pointName } from "./summary.ts";

/** A marker's label: its visible text, its spoken name, and its kind (the pin's style). */
export interface PointLabel {
  text: string;
  name: string;
  kind: "start" | "end" | "via";
}

/**
 * A marker's label: A for the start, B for the end, a number for a stop. In a
 * loop there is no B: A is the "Start and finish" and the rest are stops.
 */
export function pointLabel(index: number, count: number, loop: boolean): PointLabel {
  const name = pointName(index, count, loop);
  if (index === 0) return { text: "A", name, kind: "start" };
  if (!loop && index === count - 1 && count > 1) return { text: "B", name, kind: "end" };
  return { text: String(index), name, kind: "via" };
}

/** A click or a search put a point in: "Stop 2 added." */
export function addedSaid(index: number, count: number, loop: boolean): string {
  return `${pointName(index, count, loop)} added.`;
}

/** A point taken off the map: named as it was, from the list before the removal. */
export function removedSaid(index: number, count: number, loop: boolean): string {
  return `${pointName(index, count, loop)} removed.`;
}

/** A rail station's Start here or Add as stop. */
export function stationSaid(index: number, count: number, loop: boolean): string {
  return `${pointName(index, count, loop)} set at the station.`;
}

/**
 * A stop dragged into leg `leg` of a plan that now has `count` points. In a
 * loop the start is "the start" in this sentence ("between the start and Stop
 * 2" reads as two places; "between Start and finish and Stop 2" does not), and
 * the closing leg's far end is the start too.
 */
export function insertedSaid(leg: number, count: number, loop: boolean): string {
  const at = (index: number) => (loop && (index === 0 || index >= count) ? "the start" : pointName(index, count, loop));
  return `Stop ${leg + 1} added, between ${at(leg)} and ${at(leg + 2)}.`;
}

/**
 * Reverse pressed. A loop the rider chose has no end to speak of, even one
 * that already ends on its start (reversed whole, its two ends one place).
 */
export function reversedSaid(loop: boolean): string {
  return loop
    ? "Reversed: the loop now goes the other way around, from the same start."
    : "Reversed: the old end is now the start.";
}

/** Why Reverse does nothing in a loop of a start and one stop. */
export const REVERSE_ONE_STOP_HINT =
  "A loop with one stop is the same either way around. Add another stop to reverse it.";

/**
 * Why Reverse is unavailable when there is a ride to reverse but reversing it
 * changes nothing (a loop of a start and one stop), or null. With fewer than
 * two points it is plainly disabled.
 */
export function reverseUnavailableHint(points: readonly LonLat[], loop: boolean): string | null {
  return points.length >= 2 && !canReverse(points, loop) ? REVERSE_ONE_STOP_HINT : null;
}

/** The loop toggle turned on or off with `count` points placed: their names change, so say how. */
export function loopToggledSaid(on: boolean, count: number): string {
  if (on) return "Loop on: the start is also the finish; other points are stops.";
  return count >= 2 ? "Loop off: the last point is now the end." : "Loop off: the next point you add is the end.";
}

/** The ride type and dials that decide whether the points carry a loop's names. */
export interface LoopRide {
  preset: PresetId;
  dials: { loop?: boolean };
}

/**
 * What to say when a change of the ride renames the points, or null when it
 * does not: the loop toggle, a ride type into or out of Mass Ride (which has
 * no loop), or an undo or redo that brings another loop state back. Nothing
 * to say with no points, or when the names stay as they were.
 */
export function loopChangeSaid(before: LoopRide, after: LoopRide, count: number): string | null {
  const was = loopStops(before.preset, before.dials.loop);
  const now = loopStops(after.preset, after.dials.loop);
  if (was === now || count < 1) return null;
  return loopToggledSaid(now, count);
}

/** Where to find the toggle, said only where the ride type has one. */
const TOGGLE_PLACE = "in the ride settings (the Ride line's Edit button)";

/** The hint before any point is placed. */
export function emptyPlanHint(preset: PresetId, loop: boolean): string {
  const first = loop
    ? "Search for a place, or click the map to set a start, then add stops. The ride comes back to the start."
    : "Search for a place, or click the map to set a start, then an end. Later clicks add a stop on the nearest leg.";
  // After Clear the toggle stays on but is hidden until there is a start, so say how to get a one-way ride.
  const toggle = loop
    ? ` The "${LOOP_LABEL}" toggle is on; once the start is placed, you can turn it off ${TOGGLE_PLACE}.`
    : preset === "mass-ride"
      ? ""
      : ` Once the start is placed, you can turn on ${LOOP_LABEL} ${TOGGLE_PLACE};` +
        " then each click after the start is a stop.";
  return `${first}${toggle} ${editingTips()}`;
}

/**
 * How to change points already placed, from the mouse and the keyboard: the end of the hint before any
 * point, and the whole of "More tips" once there are points (the correctness review's N5: the start-up
 * words read wrong with points placed).
 */
export function editingTips(): string {
  return (
    "Drag any marker to move it, or drag the route line to pull it through somewhere else" +
    " (on a phone, press and hold the line first). Click a stop for Remove. From the keyboard," +
    ' move the map with the arrow keys and use "Add point at map center"; Ctrl+Z undoes the' +
    " last change and Ctrl+Shift+Z redoes it."
  );
}

/** The hint with the start alone, with the keyboard's way to place the next point. */
export function loneStartHint(preset: PresetId, loop: boolean): string {
  const keys = 'or use "Add point at map center"';
  if (loop) return `Now click the map to add a stop, ${keys}. The ride comes back to the start.`;
  if (preset === "mass-ride") return `Now click the map where you want to finish, ${keys}.`;
  return (
    `Now click the map where you want to finish, ${keys}. To finish back at the start instead,` +
    ` turn on ${LOOP_LABEL} ${TOGGLE_PLACE}.`
  );
}
