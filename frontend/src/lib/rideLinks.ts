/**
 * A LINK OPENED DURING A RIDE ASKS FIRST (the 2026-10-29 review). In the phone app a RouteMaker link tapped or shared
 * in another app opened in place of the page at once, a ride in progress included: Ride mode ended and the voice
 * stopped. The app now hands such a link to the page as an OPEN_LINK_EVENT (MainActivity.java), and the page opens it
 * at once, or, during a ride or Roam, asks first. A page without this listener does not take the event, and the app's
 * own script opens the link as before.
 */
import { t } from "./i18n.ts";

/** The event the phone app sends with a link (its `detail`), cancelable: the page takes it by cancelling it. */
export const OPEN_LINK_EVENT = "routemaker:open-link";

/** Asked before a link replaces the ride. */
export const OPEN_LINK_ASK = t("Leave your ride to open this link?");

export interface OpenLinkEnv {
  addEventListener(type: string, listener: (event: Event) => void): void;
  removeEventListener(type: string, listener: (event: Event) => void): void;
}

/**
 * Takes the app's links: opened (`go`) at once off the bike, else only when the rider says yes (`ask`). Anything that
 * is not a string is left alone. Returns the way to stop listening.
 */
export function watchOpenLinks(env: OpenLinkEnv, onBike: () => boolean, ask: (question: string) => boolean, go: (url: string) => void): () => void {
  const listener = (event: Event) => {
    const url = (event as CustomEvent<unknown>).detail;
    if (typeof url !== "string" || !url) return;
    event.preventDefault();
    if (!onBike() || ask(OPEN_LINK_ASK)) go(url);
  };
  env.addEventListener(OPEN_LINK_EVENT, listener);
  return () => env.removeEventListener(OPEN_LINK_EVENT, listener);
}
