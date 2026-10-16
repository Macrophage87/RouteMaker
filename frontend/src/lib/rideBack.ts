/**
 * A back gesture during a ride does nothing (review RIDE-2): easy to make on the bars or in gloves, it
 * would otherwise leave the page, and the ride with it. Start ride adds a history entry for the ride;
 * a back while riding lands on the entry before it, and the ride's is pushed again at once. End ride
 * takes the ride's entry off, so the history is as it was before the ride.
 */

/** Said, politely, each time a back gesture is held during a ride. */
export const STILL_RIDING_SAID = "Still riding. Use End ride to stop.";

/** The parts of `window` the guard uses. */
export interface BackWindow {
  history: Pick<History, "pushState" | "replaceState" | "back" | "state">;
  location: { href: string };
  addEventListener(type: "popstate", listener: () => void): void;
  removeEventListener(type: "popstate", listener: () => void): void;
}

const RIDE_ENTRY = { routemakerRide: true };

/** Hold the back gesture from now until the returned function is called (End ride); `held` hears each one held. */
export function holdBackDuringRide(win: BackWindow, held: () => void = () => {}): () => void {
  const push = () => win.history.pushState(RIDE_ENTRY, "", win.location.href);
  const onBack = () => {
    push();
    held();
  };
  push();
  win.addEventListener("popstate", onBack);
  return () => {
    win.removeEventListener("popstate", onBack);
    // Only the ride's own entry: one the page replaced since (a new link) stays.
    if ((win.history.state as typeof RIDE_ENTRY | null)?.routemakerRide) win.history.back();
  };
}

/**
 * At page load no ride is on: an entry a ride pushed before a reload or a closed app keeps its marker, and
 * would make a later End take it off with a back. It is marked as the page's own (review RIDE-2).
 */
export function forgetStaleRideEntry(win: Pick<BackWindow, "history" | "location">): void {
  if ((win.history.state as typeof RIDE_ENTRY | null)?.routemakerRide) win.history.replaceState(null, "", win.location.href);
}
