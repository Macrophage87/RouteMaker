/**
 * Undo and redo for the planner's point list (PLAN.md:203, "undo and redo"):
 * every edit (a click, a drag of the line or of a marker, a removal, Reverse,
 * Clear) records the list as it was, undo gives the last one back and keeps
 * the list it replaced for redo, and redo gives that back. A new edit after
 * an undo starts a new branch, so what could be redone is dropped, as in any
 * editor. A snapshot is at most 25 pairs of numbers, so keeping many costs
 * nothing; the limit only stops an afternoon of edits growing without end.
 */

export const UNDO_LIMIT = 50;

export class EditHistory<T> {
  private readonly past: T[] = [];
  private readonly future: T[] = [];
  private readonly limit: number;

  constructor(limit: number = UNDO_LIMIT) {
    this.limit = Math.max(1, limit);
  }

  /** The state before an edit. What could be redone is gone: this edit replaces it. */
  record(before: T): void {
    this.future.length = 0;
    this.past.push(before);
    if (this.past.length > this.limit) this.past.shift();
  }

  /** The state before the last edit, or undefined when there is none; `current` is kept for redo. */
  undo(current: T): T | undefined {
    const before = this.past.pop();
    if (before !== undefined) this.future.push(current);
    return before;
  }

  /** The state the last undo replaced, or undefined when there is none; `current` is kept for undo. */
  redo(current: T): T | undefined {
    const after = this.future.pop();
    if (after !== undefined) this.past.push(current);
    return after;
  }

  clear(): void {
    this.past.length = 0;
    this.future.length = 0;
  }

  get size(): number {
    return this.past.length;
  }

  get canUndo(): boolean {
    return this.past.length > 0;
  }

  get canRedo(): boolean {
    return this.future.length > 0;
  }
}

interface KeyLike {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}

/** Ctrl+Z, or Cmd+Z on a Mac; not with Shift (that is redo) and not with Alt. */
export function isUndoKey(event: KeyLike): boolean {
  return (event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey && event.key.toLowerCase() === "z";
}

/** Ctrl+Shift+Z or Cmd+Shift+Z, and Ctrl+Y (Windows' redo); not with Alt. */
export function isRedoKey(event: KeyLike): boolean {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return false;
  const key = event.key.toLowerCase();
  return (event.shiftKey && key === "z") || (!event.shiftKey && key === "y");
}

const TEXT_INPUTS = new Set(["text", "search", "email", "url", "tel", "number", "password"]);

/** Whether the focus is somewhere that has an undo of its own: a text field. */
export function typesText(target: { tagName?: string; type?: string; isContentEditable?: boolean } | null): boolean {
  if (!target) return false;
  if (target.isContentEditable) return true;
  const tag = (target.tagName ?? "").toUpperCase();
  if (tag === "TEXTAREA") return true;
  return tag === "INPUT" && TEXT_INPUTS.has((target.type ?? "text").toLowerCase());
}

export type Direction = "undo" | "redo";

/** One step through the history: undo goes back, redo forwards. */
export function step<T>(history: EditHistory<T>, direction: Direction, current: T): T | undefined {
  return direction === "undo" ? history.undo(current) : history.redo(current);
}
