/**
 * The on-screen keyboard over the bottom sheet (review UI-7). Android Chrome resizes the page for
 * the keyboard (index.html's `interactive-widget=resizes-content`); iOS Safari shrinks only the
 * visual viewport, so while a place search has the focus on a phone the app is shortened by the
 * part the keyboard covers (`--keyboard-lift`, styles.css), and the sheet sits above it.
 */

/** The parts of `window` the watch uses. */
export interface LiftWindow {
  innerHeight: number;
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

/**
 * Keep `--keyboard-lift` on `root` up to date until the returned function is called, which
 * takes it off again.
 */
export function watchKeyboard(win: LiftWindow, root: { style: Pick<CSSStyleDeclaration, "setProperty" | "removeProperty"> }): () => void {
  const view = win.visualViewport;
  if (!view) return () => {};
  const update = () => {
    const lift = keyboardLift(win);
    if (lift > 0) root.style.setProperty("--keyboard-lift", `${lift}px`);
    else root.style.removeProperty("--keyboard-lift");
  };
  update();
  view.addEventListener("resize", update);
  view.addEventListener("scroll", update);
  return () => {
    view.removeEventListener("resize", update);
    view.removeEventListener("scroll", update);
    root.style.removeProperty("--keyboard-lift");
  };
}
