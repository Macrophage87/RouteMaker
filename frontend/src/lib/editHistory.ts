/**
 * Undo for the planner's point list: every edit (a click, a drag of the line
 * or of a marker, a removal, Reverse, Clear) records the list as it was, and
 * undo gives the last one back. A snapshot is at most 25 pairs of numbers,
 * so keeping many costs nothing; the limit only stops an afternoon of edits
 * growing without end.
 */

export const UNDO_LIMIT = 50;

export class EditHistory<T> {
  private readonly past: T[] = [];
  private readonly limit: number;

  constructor(limit: number = UNDO_LIMIT) {
    this.limit = Math.max(1, limit);
  }

  /** The state before an edit. */
  record(before: T): void {
    this.past.push(before);
    if (this.past.length > this.limit) this.past.shift();
  }

  /** The state before the last edit, or undefined when there is none. */
  undo(): T | undefined {
    return this.past.pop();
  }

  clear(): void {
    this.past.length = 0;
  }

  get size(): number {
    return this.past.length;
  }

  get canUndo(): boolean {
    return this.past.length > 0;
  }
}

interface KeyLike {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}

/** Ctrl+Z, or Cmd+Z on a Mac; not Shift (redo, elsewhere) and not Alt. */
export function isUndoKey(event: KeyLike): boolean {
  return (event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey && event.key.toLowerCase() === "z";
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
