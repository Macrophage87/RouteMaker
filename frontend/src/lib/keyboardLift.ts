/**
 * The on-screen keyboard over the bottom sheet (review UI-7). Android Chrome resizes the page for
 * the keyboard (index.html's `interactive-widget=resizes-content`); iOS Safari shrinks only the
 * visual viewport, so while a place search has the focus on a phone the app is shortened by the
 * part the keyboard covers (`--keyboard-lift`, styles.css), and the sheet sits above it.
 *
 * The viewport's sizes are read again a moment after the last change, and on the window's own
 * resize: while the keyboard opens or closes the two heights move in separate steps, and a reading
 * taken between them, with no later event, left the app shortened after the keyboard had gone
 * (seen in the Android app, the search box still focused).
 */

/** The parts of `window` the watch uses. */
export interface LiftWindow {
  innerHeight: number;
  /** The window's own resize: the layout viewport can change after the visual one has stopped. */
  addEventListener?(type: "resize", listener: () => void): void;
  removeEventListener?(type: "resize", listener: () => void): void;
  setTimeout?(handler: () => void, ms: number): number;
  clearTimeout?(id: number): void;
  visualViewport?: {
    height: number;
    offsetTop: number;
    /** Pinch zoom; above 1 the visual viewport is smaller for that, not for a keyboard. */
    scale?: number;
    addEventListener(type: "resize" | "scroll", listener: () => void): void;
    removeEventListener(type: "resize" | "scroll", listener: () => void): void;
  } | null;
}

/** The height, in px, of the layout viewport below the visual one: the keyboard, or 0 (also while pinch-zoomed). */
export function keyboardLift(win: LiftWindow): number {
  const view = win.visualViewport;
  if (!view || (view.scale ?? 1) > 1) return 0;
  return Math.max(0, Math.round(win.innerHeight - view.height - view.offsetTop));
}

/** How long after the last viewport change the sizes are read once more, in ms. */
export const SETTLE_MS = 300;

/**
 * Keep `--keyboard-lift` on `root` up to date until the returned function is called, which
 * takes it off again.
 */
export function watchKeyboard(win: LiftWindow, root: { style: Pick<CSSStyleDeclaration, "setProperty" | "removeProperty"> }): () => void {
  const view = win.visualViewport;
  if (!view) return () => {};
  const measure = () => {
    const lift = keyboardLift(win);
    if (lift > 0) root.style.setProperty("--keyboard-lift", `${lift}px`);
    else root.style.removeProperty("--keyboard-lift");
  };
  let settle: number | undefined;
  const update = () => {
    measure();
    if (settle !== undefined) win.clearTimeout?.(settle);
    settle = win.setTimeout?.(measure, SETTLE_MS);
  };
  measure();
  view.addEventListener("resize", update);
  view.addEventListener("scroll", update);
  win.addEventListener?.("resize", update);
  return () => {
    view.removeEventListener("resize", update);
    view.removeEventListener("scroll", update);
    win.removeEventListener?.("resize", update);
    if (settle !== undefined) win.clearTimeout?.(settle);
    root.style.removeProperty("--keyboard-lift");
  };
}
