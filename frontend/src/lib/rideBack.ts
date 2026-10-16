/**
 * A back gesture during a ride does nothing (review RIDE-2): easy to make on the bars or in gloves, it
 * would otherwise leave the page, and the ride with it. Start ride adds a history entry for the ride;
 * a back while riding lands on the entry before it, and the ride's is pushed again at once. End ride
 * takes the ride's entry off, so the history is as it was before the ride.
 */

/** The parts of `window` the guard uses. */
export interface BackWindow {
  history: Pick<History, "pushState" | "back" | "state">;
  location: { href: string };
  addEventListener(type: "popstate", listener: () => void): void;
  removeEventListener(type: "popstate", listener: () => void): void;
}

const RIDE_ENTRY = { routemakerRide: true };

/** Hold the back gesture from now until the returned function is called (End ride). */
export function holdBackDuringRide(win: BackWindow): () => void {
  const push = () => win.history.pushState(RIDE_ENTRY, "", win.location.href);
  push();
  win.addEventListener("popstate", push);
  return () => {
    win.removeEventListener("popstate", push);
    // Only the ride's own entry: one the page replaced since (a new link) stays.
    if ((win.history.state as typeof RIDE_ENTRY | null)?.routemakerRide) win.history.back();
  };
}
