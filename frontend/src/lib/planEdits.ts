/**
 * The plan's two ways of changing its points, as App.tsx wires them: an edit
 * (`commit`), which the history records so undo can give the points before it
 * back, and undo or redo (`travel`), which is not itself an edit. Kept out of
 * the component so a test runs App's own versions (MERGE-SEARCH re-check R15:
 * a commit that forgot to record broke undo for every edit, and no test ran
 * App's commit).
 */
import { EditHistory, step, type Direction } from "./editHistory.ts";

export interface PlanEditDeps<T> {
  history: EditHistory<T>;
  /** The points now, including an edit made since the last render. */
  current(): T;
  /** Make `next` the points, at once and for the next render. */
  set(next: T): void;
  /** The history changed: Undo and Redo may have come or gone. */
  sync(): void;
}

export interface PlanEdits<T> {
  /** Every edit of the points goes through here, so undo can give the list before it back. */
  commit(next: T): void;
  /** Undo or redo: the points the history gives back, or undefined when it has none. */
  travel(direction: Direction): T | undefined;
}

export function planEdits<T>(deps: PlanEditDeps<T>): PlanEdits<T> {
  return {
    commit(next) {
      deps.history.record(deps.current());
      deps.sync();
      deps.set(next);
    },
    travel(direction) {
      const next = step(deps.history, direction, deps.current());
      if (next === undefined) return undefined;
      deps.sync();
      deps.set(next);
      return next;
    },
  };
}

/** What a screen reader hears after an undo or a redo. */
export function travelSaid(direction: Direction, pointCount: number): string {
  const count = `${pointCount} ${pointCount === 1 ? "point" : "points"}`;
  return `${direction === "undo" ? "Undone" : "Redone"}. The route has ${count}.`;
}
