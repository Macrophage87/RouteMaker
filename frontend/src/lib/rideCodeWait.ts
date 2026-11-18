/**
 * Start or Resume pressed before Ride mode's code is in (app/later.tsx, #1333): one wait at a time, a second press
 * ignored. While it waits the pressed button shows busy and "Opening Ride…" is said; once in, the press carries on;
 * where the code cannot come, the rider stays where they were and is told (`failed`).
 */
import { t } from "./i18n.ts";

export const OPENING_RIDE = t("Opening Ride…");

export type RideCodeWaiter<W> = (which: W, go: () => void) => void;

export function rideCodeWaiter<W>(
  load: () => Promise<unknown>,
  on: { waiting: (which: W | null) => void; announce: (text: string) => void; failed: string },
): RideCodeWaiter<W> {
  let pending = false;
  return (which, go) => {
    if (pending) return;
    pending = true;
    on.waiting(which);
    on.announce(OPENING_RIDE);
    load().then(
      () => {
        pending = false;
        on.waiting(null);
        go();
      },
      () => {
        pending = false;
        on.waiting(null);
        on.announce(on.failed);
      },
    );
  };
}
