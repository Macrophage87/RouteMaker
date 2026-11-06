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
 * typed (a Detour search, Alert's Other, its microphone listening), and anything asking (Alert's Send to everyone?, Already
 * done?, a stop's name, Resume), a dialog with the focus in it (Ride settings, the join sheet), and a map card or
 * side menu with a key's or a screen reader's focus in it (InputWay; a finger's tap focuses too, and still closes). The group's question, asked as the ride starts, closes as its No (the 2026-10-28 audit,
 * P6: it never stays over the ride's buttons). Accessibility mode closes nothing on its own: a screen
 * reader's reading touches nothing. A menu closed with the focus in it hands the focus to its toggle; a map card, to
 * the map.
 */

/** How long the screen is left alone before the map goes back to the rider. */
export const IDLE_RECENTRE_MS = 30_000;

/**
 * What counts as touching the screen: the 30 s count from a finger lifted, so a long pinch is not cut short. The focus
 * moving counts too: a screen reader's swipe from one control to the next moves it without a pointer or a key.
 */
export const IDLE_TOUCH_EVENTS = ["pointerdown", "pointerup", "wheel", "keydown", "focusin"] as const;

/**
 * An open panel during a ride or Roam: a toggle shown expanded within the ride's screen or the group bar, the group's
 * question, an open dialog, or the map's Help panel shown. MapLibre's compact credits (ours at every width, MapView)
 * are shown with maplibregl-compact-show; their details element carries `open` while folded to the "i", so `[open]`
 * there held the map off the rider for good (found 2026-10-28 with a ride's Show on map).
 */
export const RIDE_PANEL_OPEN =
  '.ride [aria-expanded="true"], .ride-group [aria-expanded="true"], .ride-consent, dialog[open], .maplibregl-ctrl-attrib.maplibregl-compact-show';

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
/** The value of IDLE_CLOSE_ATTR on a dialog that closes even with the focus in it (a question whose close is its No). */
export const IDLE_CLOSE_ALWAYS = "always";

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

/** A focus move this long after a finger's touch is the touch's (a menu focusing its heading as it opens). */
export const TOUCH_FOCUS_MS = 1000;

/**
 * How the focus got where it is: by a key or a screen reader's move (true), or by a finger (false). Not
 * `:focus-visible`, which a browser may match on a heading a menu focuses by script as a tap opens it (iOS Safari), so
 * a tapped menu would never close. A key pressed counts as a key; a focus move with no touch just before it, as a
 * screen reader's; a touch, as a finger's, until the next key or untouched move.
 */
export class InputWay {
  private keyed = false;
  private touchedAt = -Infinity;
  private readonly now: () => number;
  constructor(now: () => number = () => Date.now()) {
    this.now = now;
  }
  touch(): void {
    this.keyed = false;
    this.touchedAt = this.now();
  }
  key(): void {
    this.keyed = true;
  }
  focus(): void {
    if (this.now() - this.touchedAt > TOUCH_FOCUS_MS) this.keyed = true;
  }
  /** The focus is a key's or a screen reader's: what holds it is being read or used. */
  keyFocus(): boolean {
    return this.keyed;
  }
}

/** The page's: kept by watchIdleRecentre, read by closeIdlePanels. */
export const INPUT_WAY = new InputWay();

/**
 * Close what a screen left alone closes (above): the map's cards, the road info and the ride's side menus, each by
 * its own close (its X, its toggle, the dialog's close), so each puts things back as a press would. Whether any closed.
 */
export function closeIdlePanels(doc: Document, keyFocus: () => boolean = () => INPUT_WAY.keyFocus()): boolean {
  // A map card or side menu with a key's or a screen reader's focus in it is being read or used: it stays, as a
  // dialog does. A finger's tap focuses too, and that one still lets it close.
  const focusShown = (active: Element | null) => active !== null && keyFocus();
  let closed = false;
  const active = doc.activeElement;
  const lost = () => doc.activeElement === null || doc.activeElement === doc.body;
  for (const button of doc.querySelectorAll<HTMLElement>(MAP_CARD_CLOSE)) {
    const card = button.closest(".maplibregl-popup");
    if (!card || typingIn(card, active)) continue;
    const held = card.contains(active);
    if (held && focusShown(active)) continue;
    button.click();
    closed = true;
    if (held && lost()) doc.querySelector<HTMLElement>(".maplibregl-canvas")?.focus({ preventScroll: true });
  }
  for (const toggle of doc.querySelectorAll<HTMLElement>(`[${IDLE_CLOSE_ATTR}][aria-expanded="true"]`)) {
    const panel = doc.getElementById(toggle.getAttribute("aria-controls") ?? "");
    if (panel && typingIn(panel, active)) continue;
    const held = (panel?.contains(active) ?? false) || toggle === active;
    if (held && focusShown(active)) continue;
    toggle.click();
    closed = true;
    if (held) toggle.focus({ preventScroll: true });
  }
  for (const dialog of doc.querySelectorAll<HTMLDialogElement>(`dialog[open][${IDLE_CLOSE_ATTR}]`)) {
    // A dialog with the focus in it is being read or used (a screen reader's reading touches nothing): it stays. The
    // group's question (IDLE_CLOSE_ALWAYS) closes as its No all the same, so it never stays over the ride's buttons.
    if ((dialog.getAttribute(IDLE_CLOSE_ATTR) !== IDLE_CLOSE_ALWAYS && dialog.contains(active)) || typingIn(dialog, active)) continue;
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
export function watchIdleRecentre(win: IdleWindow, watch: IdleRecentre, idleMs: number = IDLE_RECENTRE_MS, way: InputWay = INPUT_WAY): () => void {
  let timer: number | null = null;
  // The focus a close moves (to a toggle, the map) is no one's input.
  let closing = false;
  const arm = () => {
    if (timer !== null) win.clearTimeout(timer);
    timer = win.setTimeout(fire, idleMs);
  };
  const fire = () => {
    timer = null;
    closing = true;
    let closed: boolean | undefined;
    try {
      closed = watch.closePanels?.();
    } finally {
      closing = false;
    }
    if (closed) {
      // Closing a panel that held the focus moves the focus (to its toggle, the map, or back from a dialog), and that
      // focusin armed a fresh 30 s: cleared, or it would be left running and close the next menu early.
      if (timer !== null) win.clearTimeout(timer);
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
  const touched = () => way.touch();
  const keyed = () => way.key();
  const focused = () => !closing && way.focus();
  for (const type of IDLE_TOUCH_EVENTS) win.addEventListener(type, arm, options);
  win.addEventListener("pointerdown", touched, options);
  win.addEventListener("keydown", keyed, options);
  win.addEventListener("focusin", focused, options);
  arm();
  return () => {
    for (const type of IDLE_TOUCH_EVENTS) win.removeEventListener(type, arm, options);
    win.removeEventListener("pointerdown", touched, options);
    win.removeEventListener("keydown", keyed, options);
    win.removeEventListener("focusin", focused, options);
    if (timer !== null) win.clearTimeout(timer);
    timer = null;
  };
}
