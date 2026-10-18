/**
 * Reordering the plan's points by hand (Stephen 2026-10-18: "In addition to best order, allow the stops to be
 * dragged and dropped too"): each row's grip in the points list (lib/pointsList.ts).
 *
 * Three ways, one result (App.tsx reorderPoint, one edit that Undo takes back):
 * - drag the grip, with a finger or a mouse (pointer events, so it works on Android, where HTML drag and drop
 *   does not); the rows slide aside as it passes, and nothing moves in the DOM until the drop;
 * - the up and down arrows on the focused grip;
 * - a press of the grip (a double tap with TalkBack) shows Move up, Move down and Done in that row.
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

/** How far row `index` is moved while row `from` is dragged over `over` (the others slide aside to make room). */
export function rowShift(index: number, drag: { from: number; over: number; dy: number; height: number }): number {
  const { from, over, dy, height } = drag;
  if (index === from) return dy;
  if (from < index && index <= over) return -height;
  if (over <= index && index < from) return height;
  return 0;
}

/** A drag only starts past this many pixels, so a press is a press. */
const DRAG_START_PX = 6;

export interface PointMover {
  /** The drag under way, for each row's shift; null otherwise. */
  drag: { from: number; over: number; dy: number; height: number } | null;
  /** The row showing Move up, Move down and Done, or null. */
  moving: number | null;
  /** The grip's handlers and ref for row `index`. */
  grip(index: number): {
    ref: (button: HTMLButtonElement | null) => void;
    onPointerDown: (event: PointerEvent<HTMLButtonElement>) => void;
    onPointerMove: (event: PointerEvent<HTMLButtonElement>) => void;
    onPointerUp: (event: PointerEvent<HTMLButtonElement>) => void;
    onPointerCancel: () => void;
    onClick: () => void;
    onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
  };
  /** Move up or Move down in the row showing them; the focus stays on the button pressed, in the row's new place. */
  step(index: number, by: -1 | 1): void;
  /** A Move up or Move down button, for that focus. */
  stepRef(index: number, by: -1 | 1, button: HTMLButtonElement | null): void;
  /** Done: the row's buttons go, and the focus goes back to its grip. */
  done(index: number): void;
}

export function usePointMover(count: number, onMove: (from: number, to: number) => void): PointMover {
  const [drag, setDrag] = useState<PointMover["drag"]>(null);
  const [moving, setMoving] = useState<number | null>(null);
  const dragRef = useRef<PointMover["drag"]>(null);
  const rows = useRef<Array<{ top: number; height: number }>>([]);
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
  // A point removed or added under an open Move up / Move down closes it.
  useEffect(() => {
    setMoving((now) => (now !== null && now >= count ? null : now));
  }, [count]);

  const keep = (key: string, button: HTMLButtonElement | null) => {
    if (button) buttons.current.set(key, button);
    else buttons.current.delete(key);
  };
  const moveTo = (from: number, to: number, focus: string[]) => {
    if (to < 0 || to >= count || to === from) return;
    focusNext.current = focus;
    setMoving((now) => (now === from ? to : now));
    onMove(from, to);
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
        rows.current = Array.from(list.children, (row) => {
          const box = row.getBoundingClientRect();
          return { top: box.top, height: box.height };
        });
        startY.current = event.clientY;
        dragged.current = false;
        event.currentTarget.setPointerCapture?.(event.pointerId);
        show({ from: index, over: index, dy: 0, height: rows.current[index]?.height ?? 0 });
      },
      onPointerMove: (event) => {
        const now = dragRef.current;
        if (!now) return;
        const dy = event.clientY - startY.current;
        if (!dragged.current && Math.abs(dy) < DRAG_START_PX) return;
        dragged.current = true;
        const row = rows.current[now.from];
        const over = row ? dropIndex(rows.current, now.from, row.top + row.height / 2 + dy) : now.from;
        show({ ...now, over, dy });
      },
      onPointerUp: (event) => {
        const now = dragRef.current;
        event.currentTarget.releasePointerCapture?.(event.pointerId);
        show(null);
        if (!now || !dragged.current) return;
        // The click that follows a mouse's drag is not a press (a finger's drag has none, so it is forgotten at once).
        swallowClick.current = true;
        window.setTimeout(() => {
          swallowClick.current = false;
        }, 0);
        moveTo(now.from, now.over, [`grip${now.over}`]);
      },
      onPointerCancel: () => show(null),
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
          moveTo(index, to, [`grip${to}`]);
        } else if (event.key === "Escape" && moving === index) {
          event.preventDefault();
          setMoving(null);
        }
      },
    }),
    step: (index, by) => moveTo(index, index + by, [`step${by}:${index + by}`, `step${-by}:${index + by}`, `grip${index + by}`]),
    stepRef: (index, by, button) => keep(`step${by}:${index}`, button),
    done: (index) => {
      setMoving(null);
      focusNext.current = [`grip${index}`];
    },
  };
}
