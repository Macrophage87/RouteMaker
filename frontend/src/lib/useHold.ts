// Holding a button (lib/broadcastQr.ts): a press held HOLD_MS, a right-click, or the keyboard's menu key does the hold,
// and the click that ends a held press does nothing.
import { useRef, type KeyboardEvent, type MouseEvent, type PointerEvent } from "react";
import { HOLD_MS } from "./broadcastQr.ts";

export interface HoldHandlers {
  onPointerDown?: (event: PointerEvent) => void;
  onPointerUp?: () => void;
  onPointerLeave?: () => void;
  onPointerCancel?: () => void;
  onContextMenu?: (event: MouseEvent) => void;
  onClickCapture?: (event: MouseEvent) => void;
  onKeyDown?: (event: KeyboardEvent) => void;
}

/** The button's handlers for `onHold`; none without one. */
export function useHold(onHold: (() => void) | null | undefined, ms = HOLD_MS): HoldHandlers {
  const timer = useRef<number | null>(null);
  // This press was held: its click is swallowed (and a long press's own context menu is not a second hold).
  const held = useRef(false);
  const clear = () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  };
  if (!onHold) return {};
  const fire = () => {
    clear();
    if (held.current) return;
    held.current = true;
    onHold();
  };
  return {
    onPointerDown: (event) => {
      held.current = false;
      clear();
      if (event.button === 0) timer.current = window.setTimeout(fire, ms);
    },
    onPointerUp: clear,
    onPointerLeave: clear,
    onPointerCancel: clear,
    onContextMenu: (event) => {
      event.preventDefault();
      fire();
    },
    onClickCapture: (event) => {
      if (!held.current) return;
      held.current = false;
      event.preventDefault();
      event.stopPropagation();
    },
    // A key press is its own press (a held pointer press before it is over).
    onKeyDown: () => {
      held.current = false;
    },
  };
}
