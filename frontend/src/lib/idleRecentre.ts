/**
 * Back to the ride's own view when left alone (the owner, 2026-10-24: "If you don't have a panel open and haven't
 * touched the screen while riding, go back to the default tracking view", "for 30 seconds"). After the rider moves
 * the map by hand (a pan, a pinch, a turn), 30 s with no touch, wheel or key and no panel open puts the map back on
 * the rider: following again, at the ride's zoom, track-up as chosen. Any touch starts the 30 s again; a panel open
 * when they run out (a side menu, the settings, the riders, an alert, a question, a dialog) holds it for another 30 s.
 * No button: Where am I? still does it at once.
 */

/** How long the screen is left alone before the map goes back to the rider. */
export const IDLE_RECENTRE_MS = 30_000;

/** What counts as touching the screen: the 30 s count from a finger lifted, so a long pinch is not cut short. */
export const IDLE_TOUCH_EVENTS = ["pointerdown", "pointerup", "wheel", "keydown"] as const;

/**
 * An open panel during a ride or Roam: a toggle shown expanded within the ride's screen or the group bar, the group's
 * question, or an open dialog.
 */
export const RIDE_PANEL_OPEN = '.ride [aria-expanded="true"], .ride-group [aria-expanded="true"], .ride-consent, dialog[open]';

/** The parts of `window` the watch uses. */
export interface IdleWindow {
  addEventListener(type: string, listener: () => void, options?: AddEventListenerOptions): void;
  removeEventListener(type: string, listener: () => void, options?: EventListenerOptions): void;
  setTimeout(handler: () => void, ms: number): number;
  clearTimeout(id: number): void;
}

export interface IdleRecentre {
  /** The map is off the ride's view (it stopped following, or was pinched or turned by hand). */
  away(): boolean;
  /** A panel is open, so the map stays where it is. */
  panelOpen(): boolean;
  /** Put the map back on the rider. */
  recentre(): void;
}

/** Watch from now until the returned function is called (the ride or Roam over). */
export function watchIdleRecentre(win: IdleWindow, watch: IdleRecentre, idleMs: number = IDLE_RECENTRE_MS): () => void {
  let timer: number | null = null;
  const arm = () => {
    if (timer !== null) win.clearTimeout(timer);
    timer = win.setTimeout(fire, idleMs);
  };
  const fire = () => {
    timer = null;
    if (!watch.away()) return arm();
    if (watch.panelOpen()) return arm();
    watch.recentre();
    arm();
  };
  // Capture, so a touch the map or a button keeps to itself still counts; passive, so scrolling is never held.
  const options = { capture: true, passive: true };
  for (const type of IDLE_TOUCH_EVENTS) win.addEventListener(type, arm, options);
  arm();
  return () => {
    for (const type of IDLE_TOUCH_EVENTS) win.removeEventListener(type, arm, options);
    if (timer !== null) win.clearTimeout(timer);
    timer = null;
  };
}
