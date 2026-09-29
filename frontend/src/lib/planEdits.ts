/**
 * The plan's two ways of changing its points, as App.tsx wires them: an edit
 * (`commit`), which the history records so undo can give the points before it
 * back, and undo or redo (`travel`), which is not itself an edit. Kept out of
 * the component so a test runs App's own versions (MERGE-SEARCH re-check R15:
 * a commit that forgot to record broke undo for every edit, and no test ran
 * App's commit).
 *
 * An edit that also sets the ride - the ride type or the opened file, as a
 * GPX import or Clear does - records the ride as it was too, and undo restores
 * both: one step. The history holds snapshots, `{points}` or `{points, ride}`.
 */
import { EditHistory, step, type Direction } from "./editHistory.ts";

/** One entry of the undo history. */
export interface Snapshot<P, R> {
  points: P;
  ride?: R;
}

export interface PlanEditDeps<P, R> {
  history: EditHistory<Snapshot<P, R>>;
  /** The points now, including an edit made since the last render. */
  current(): P;
  /** The ride now. */
  ride(): R;
  /** Make `next` the points, at once and for the next render. */
  set(next: P): void;
  /** Make `ride` the ride. */
  applyRide(ride: R): void;
  /** The history changed: Undo and Redo may have come or gone. */
  sync(): void;
}

export interface PlanEdits<P, R> {
  /** Every edit of the points goes through here, so undo can give the list before it back. */
  commit(next: P, ride?: R): void;
  /** Undo or redo: the points the history gives back, or undefined when it has none. */
  travel(direction: Direction): P | undefined;
}

export function planEdits<P, R>(deps: PlanEditDeps<P, R>): PlanEdits<P, R> {
  return {
    commit(next, ride) {
      const before = deps.current();
      deps.history.record(ride ? { points: before, ride: deps.ride() } : { points: before });
      deps.sync();
      deps.set(next);
      if (ride) deps.applyRide(ride);
    },
    travel(direction) {
      const current: Snapshot<P, R> = { points: deps.current() };
      const next = step(deps.history, direction, current);
      if (next === undefined) return undefined;
      // The step carried a ride: the entry kept for the way back (now on the
      // other stack) carries the one it replaces.
      if (next.ride !== undefined) {
        current.ride = deps.ride();
        deps.applyRide(next.ride);
      }
      deps.sync();
      deps.set(next.points);
      return next.points;
    },
  };
}

/** What a screen reader hears after an undo or a redo. */
export function travelSaid(direction: Direction, pointCount: number): string {
  const count = `${pointCount} ${pointCount === 1 ? "point" : "points"}`;
  return `${direction === "undo" ? "Undone" : "Redone"}. The route has ${count}.`;
}
