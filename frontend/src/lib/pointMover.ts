/**
 * Reordering the plan's stops by hand (Stephen 2026-10-18: "In addition to best order, allow the stops to be
 * dragged and dropped too"): a grip on each stop's row in the points list (lib/pointsList.ts).
 *
 * Only the stops move, as with Best order: the start and the end stay, and a via point goes with the stop it leads
 * to (App.tsx reorderPoint, lib/pointKinds.ts stopsOnly). So the hook counts in stops ("slots"): slot 0 is the first
 * stop's row, wherever via points put it in the list.
 *
 * Three ways, one result (one edit that Undo takes back):
 * - drag the grip, with a finger or a mouse (pointer events, so it works on Android, where HTML drag and drop
 *   does not); the other stops slide aside as it passes, and nothing moves in the DOM until the drop;
 * - the up and down arrows on the focused grip;
 * - a press of the grip (a double tap with TalkBack) shows Up, Down and Done in that row.
 * Written without JSX, as the list is, so `node --test` reads it.
 */
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

/** The list with the item at `from` taken out and put back at `to`. */
export function reorder<T>(list: readonly T[], from: number, to: number): T[] {
  const next = list.slice();
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

/** Where a dragged row would land: past every other row whose middle is above the dragged row's middle. */
export function dropIndex(rows: ReadonlyArray<{ top: number; height: number }>, from: number, centre: number): number {
  let over = 0;
  rows.forEach((row, index) => {
    if (index !== from && row.top + row.height / 2 < centre) over += 1;
  });
  return over;
}

export interface Drag {
  from: number;
  over: number;
  dy: number;
  /** Each stop row's top when the drag began: a passed row slides to its neighbour's place (via rows between stay). */
  tops: readonly number[];
}

/** How far stop `slot` is moved while stop `from` is dragged over `over`: the dragged one follows the pointer. */
export function rowShift(slot: number, drag: Drag): number {
  const { from, over, dy, tops } = drag;
  if (slot === from) return dy;
  if (from < slot && slot <= over) return tops[slot - 1] - tops[slot];
  if (over <= slot && slot < from) return tops[slot + 1] - tops[slot];
  return 0;
}

/** A drag only starts past this many pixels, so a press is a press. */
const DRAG_START_PX = 6;

export interface PointMover {
  /** The drag under way (in stops), for each row's shift; null otherwise. */
  drag: Drag | null;
  /** The stop showing Up, Down and Done, or null. */
  moving: number | null;
  /** The grip's handlers and ref for stop `index`. */
  grip(index: number): {
    ref: (button: HTMLButtonElement | null) => void;
    onPointerDown: (event: PointerEvent<HTMLButtonElement>) => void;
    onPointerMove: (event: PointerEvent<HTMLButtonElement>) => void;
    onPointerUp: (event: PointerEvent<HTMLButtonElement>) => void;
    onPointerCancel: () => void;
    onClick: () => void;
    onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
  };
  /** Up or Down in the row showing them; the focus stays on the button pressed, in the row's new place. */
  step(index: number, by: -1 | 1): void;
  /** An Up or Down button, for that focus. */
  stepRef(index: number, by: -1 | 1, button: HTMLButtonElement | null): void;
  /** Done: the row's buttons go, and the focus goes back to its grip. */
  done(index: number): void;
}

/**
 * `slots`: each stop's row in the list. `onMove(from, to, by)`: stop `from` to stop `to`'s place, by a drag or a key;
 * after a key the focus moves with the stop, and its new name says where it is, so App says nothing more.
 * `points`: the plan, so a change from elsewhere (Undo, a removal) puts an open Up and Down away.
 */
export function usePointMover(slots: readonly number[], onMove: (from: number, to: number, by: "drag" | "key") => void, points: unknown): PointMover {
  const count = slots.length;
  const [drag, setDrag] = useState<PointMover["drag"]>(null);
  const [moving, setMoving] = useState<number | null>(null);
  const dragRef = useRef<PointMover["drag"]>(null);
  const rows = useRef<Array<{ top: number; height: number }>>([]);
  const pending = useRef<{ from: number; pointer: number } | null>(null);
  const ownMove = useRef(false);
  const startY = useRef(0);
  const dragged = useRef(false);
  const swallowClick = useRef(false);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const focusNext = useRef<string[] | null>(null);

  // After a move the list renders again with the point in its new place: the focus follows it.
  useEffect(() => {
    if (focusNext.current === null) return;
    const keys = focusNext.current;
    focusNext.current = null;
    // The first of them there: Move up is gone at the top, Move down at the bottom.
    for (const key of keys) {
      const button = buttons.current.get(key);
      if (button) return button.focus();
    }
  });
  // The plan changed from elsewhere (Undo, a removal, a new stop) under an open Up and Down: it closes, as the stop
  // it was open on may be another one now. Its own moves keep it open on the moved stop.
  useEffect(() => {
    if (ownMove.current) {
      ownMove.current = false;
      return;
    }
    setMoving(null);
  }, [points]);

  const keep = (key: string, button: HTMLButtonElement | null) => {
    if (button) buttons.current.set(key, button);
    else buttons.current.delete(key);
  };
  const moveTo = (from: number, to: number, focus: string[], by: "drag" | "key") => {
    if (to < 0 || to >= count || to === from) return;
    focusNext.current = focus;
    ownMove.current = true;
    setMoving((now) => (now === from ? to : now));
    onMove(from, to, by);
  };
  const show = (next: PointMover["drag"]) => {
    dragRef.current = next;
    setDrag(next);
  };

  return {
    drag,
    moving,
    grip: (index) => ({
      ref: (button) => keep(`grip${index}`, button),
      onPointerDown: (event) => {
        if (event.pointerType === "mouse" && event.button !== 0) return;
        const list = event.currentTarget.closest("ol");
        if (!list) return;
        // The sheet under the list has drags of its own (Go's bottom sheet): this one is the grip's.
        event.stopPropagation();
        const children = Array.from(list.children);
        rows.current = slots.map((row) => {
          const box = children[row]?.getBoundingClientRect();
          return { top: box?.top ?? 0, height: box?.height ?? 0 };
        });
        startY.current = event.clientY;
        dragged.current = false;
        event.currentTarget.setPointerCapture?.(event.pointerId);
        // Shown only once it is a drag: a tap (TalkBack's double tap too) draws nothing.
        pending.current = { from: index, pointer: event.pointerId };
      },
      onPointerMove: (event) => {
        const from = dragRef.current?.from ?? pending.current?.from;
        if (from === undefined) return;
        const dy = event.clientY - startY.current;
        if (!dragged.current && Math.abs(dy) < DRAG_START_PX) return;
        dragged.current = true;
        const row = rows.current[from];
        const over = row ? dropIndex(rows.current, from, row.top + row.height / 2 + dy) : from;
        show({ from, over, dy, tops: rows.current.map((r) => r.top) });
      },
      onPointerUp: (event) => {
        const now = dragRef.current;
        pending.current = null;
        event.currentTarget.releasePointerCapture?.(event.pointerId);
        show(null);
        if (!now || !dragged.current) return;
        // The click that follows a mouse's drag is not a press (a finger's drag has none, so it is forgotten at once).
        swallowClick.current = true;
        window.setTimeout(() => {
          swallowClick.current = false;
        }, 0);
        moveTo(now.from, now.over, [`grip${now.over}`], "drag");
      },
      onPointerCancel: () => {
        pending.current = null;
        show(null);
      },
      onClick: () => {
        if (swallowClick.current) {
          swallowClick.current = false;
          return;
        }
        setMoving((now) => (now === index ? null : index));
      },
      onKeyDown: (event) => {
        if (event.key === "ArrowUp" || event.key === "ArrowDown") {
          event.preventDefault();
          const to = index + (event.key === "ArrowUp" ? -1 : 1);
          moveTo(index, to, [`grip${to}`], "key");
        } else if (event.key === "Escape" && moving === index) {
          event.preventDefault();
          setMoving(null);
        }
      },
    }),
    step: (index, by) => moveTo(index, index + by, [`step${by}:${index + by}`, `step${-by}:${index + by}`, `grip${index + by}`], "key"),
    stepRef: (index, by, button) => keep(`step${by}:${index}`, button),
    done: (index) => {
      setMoving(null);
      focusNext.current = [`grip${index}`];
    },
  };
}
