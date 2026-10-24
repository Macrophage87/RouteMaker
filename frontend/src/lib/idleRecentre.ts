/**
 * Back to the ride's own view when left alone (the owner, 2026-10-24: "If you don't have a panel open and haven't
 * touched the screen while riding, go back to the default tracking view", "for 30 seconds"). After the rider moves
 * the map by hand (a pan, a pinch, a turn), 30 s with no touch, wheel or key and no panel open puts the map back on
 * the rider: following again, at the ride's zoom, track-up as chosen. Any touch starts the 30 s again; a panel open
 * when they run out (a side menu, the settings, the riders, an alert, a question, a dialog, the map's Help) holds it for another 30 s.
 * No button: Where am I? still does it at once.
 *
 * The cards and side menus close the same way (the owner, 2026-10-24: "Some of the various popups that you click on
 * during a ride have very small x's. Maybe auto close after 30 seconds without a screen touch?"): 30 s untouched closes
 * a map card (a stop, a place, a station, a closure, a climb), the road info, and the side menus (Detour, More, the
 * dock, 311, the riders, Alert), so the map then goes back to the rider. Kept open: a menu with words typed or being
 * typed (a Detour search, Alert's Other, its microphone listening), and anything asking (Already done?, a stop's name, the group's question,
 * Resume). Accessibility mode closes nothing on its own: a screen reader's reading touches nothing. A card closed
 * with the focus in it hands the focus to its opener, or the map.
 */

/** How long the screen is left alone before the map goes back to the rider. */
export const IDLE_RECENTRE_MS = 30_000;

/** What counts as touching the screen: the 30 s count from a finger lifted, so a long pinch is not cut short. */
export const IDLE_TOUCH_EVENTS = ["pointerdown", "pointerup", "wheel", "keydown"] as const;

/**
 * An open panel during a ride or Roam: a toggle shown expanded within the ride's screen or the group bar, the group's
 * question, or an open dialog.
 */
export const RIDE_PANEL_OPEN =
  '.ride [aria-expanded="true"], .ride-group [aria-expanded="true"], .ride-consent, dialog[open], .maplibregl-ctrl-attrib[open]';

/**
 * The follow camera's zoom at a fix: the ride's own after the screen was left alone (`reset`); kept while following
 * (a pinch out stays); closed in to the ride's own at least as following starts.
 */
export function followZoom(reset: boolean, following: boolean, current: number, rideZoom: number): number {
  if (reset) return rideZoom;
  return following ? current : Math.max(current, rideZoom);
}

/** The parts of `window` the watch uses. */
export interface IdleWindow {
  addEventListener(type: string, listener: () => void, options?: AddEventListenerOptions): void;
  removeEventListener(type: string, listener: () => void, options?: EventListenerOptions): void;
  setTimeout(handler: () => void, ms: number): number;
  clearTimeout(id: number): void;
}

/** Marks a side menu's toggle, or a dialog, that a screen left alone closes (closeIdlePanels). */
export const IDLE_CLOSE_ATTR = "data-idle-close";

/** A map card with its close button: maplibre's popups. */
const MAP_CARD_CLOSE = ".maplibregl-popup .maplibregl-popup-close-button";

/** Where words are typed: one holding words, or with the focus, keeps its menu open. */
const TEXT_FIELDS =
  'input:not([type]), input[type="text"], input[type="search"], input[type="email"], input[type="tel"], input[type="url"], input[type="number"], textarea, [contenteditable="true"]';

/** Marks something under way within a menu (the microphone listening): the menu stays open. */
export const IDLE_HOLD_ATTR = "data-idle-hold";

/** Words typed, or being typed, or something under way, within `box`: it stays open. */
export function typingIn(box: Element, active: Element | null): boolean {
  if (box.querySelector(`[${IDLE_HOLD_ATTR}]`) !== null) return true;
  for (const field of box.querySelectorAll(TEXT_FIELDS)) {
    if (field === active) return true;
    const value = "value" in field ? String(field.value) : field.textContent;
    if ((value ?? "").trim() !== "") return true;
  }
  return false;
}

/**
 * Close what a screen left alone closes (above): the map's cards, the road info and the ride's side menus, each by
 * its own close (its X, its toggle, the dialog's close), so each puts things back as a press would. Whether any closed.
 */
export function closeIdlePanels(doc: Document): boolean {
  let closed = false;
  const active = doc.activeElement;
  const lost = () => doc.activeElement === null || doc.activeElement === doc.body;
  for (const button of doc.querySelectorAll<HTMLElement>(MAP_CARD_CLOSE)) {
    const card = button.closest(".maplibregl-popup");
    if (!card || typingIn(card, active)) continue;
    const held = card.contains(active);
    button.click();
    closed = true;
    if (held && lost()) doc.querySelector<HTMLElement>(".maplibregl-canvas")?.focus({ preventScroll: true });
  }
  for (const toggle of doc.querySelectorAll<HTMLElement>(`[${IDLE_CLOSE_ATTR}][aria-expanded="true"]`)) {
    const panel = doc.getElementById(toggle.getAttribute("aria-controls") ?? "");
    if (panel && typingIn(panel, active)) continue;
    const held = panel?.contains(active) ?? false;
    toggle.click();
    closed = true;
    if (held) toggle.focus({ preventScroll: true });
  }
  for (const dialog of doc.querySelectorAll<HTMLDialogElement>(`dialog[open][${IDLE_CLOSE_ATTR}]`)) {
    if (typingIn(dialog, active)) continue;
    // Its own close handler gives the focus back (RoadInfoDialog).
    dialog.close();
    closed = true;
  }
  return closed;
}

export interface IdleRecentre {
  /** The map is off the ride's view (it stopped following, or was pinched or turned by hand). */
  away(): boolean;
  /** A panel is open, so the map stays where it is. */
  panelOpen(): boolean;
  /** Put the map back on the rider. */
  recentre(): void;
  /** Close the cards and menus a screen left alone closes (closeIdlePanels); whether any closed. */
  closePanels?(): boolean;
}

/** How long a closed menu is given to leave the page before the map is put back. */
export const IDLE_CLOSE_SETTLE_MS = 100;

/** Watch from now until the returned function is called (the ride or Roam over). */
export function watchIdleRecentre(win: IdleWindow, watch: IdleRecentre, idleMs: number = IDLE_RECENTRE_MS): () => void {
  let timer: number | null = null;
  const arm = () => {
    if (timer !== null) win.clearTimeout(timer);
    timer = win.setTimeout(fire, idleMs);
  };
  const fire = () => {
    timer = null;
    if (watch.closePanels?.()) {
      timer = win.setTimeout(settle, IDLE_CLOSE_SETTLE_MS);
      return;
    }
    settle();
  };
  const settle = () => {
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
