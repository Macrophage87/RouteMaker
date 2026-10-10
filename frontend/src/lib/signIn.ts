/**
 * Keeping a signed-out plan across the Discord sign-in round trip.
 *
 * /auth/login goes to Discord and the callback lands on "/", which loses the
 * URL fragment the plan lives in. The plan is not put in a `next` parameter:
 * that would send the points to our server's logs and to Discord. It goes in
 * this tab's sessionStorage just before the link is followed, and is read back
 * once, on a load that has no plan of its own. A bfcache restore (`pageshow` with
 * `persisted`, App.tsx) drops it, since that Back never loads the page again.
 */
export const PLAN_KEY = "routemaker.plan-before-sign-in";

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export function rememberPlan(storage: StorageLike | null, hash: string): void {
  if (!storage) return;
  // A plan with no points keeps nothing, and drops an older kept plan: the rider cleared it,
  // and a kept copy must not bring it back on the next load (the correctness re-check's C8).
  if (!/[#&]p=/.test(hash)) {
    forgetPlan(storage);
    return;
  }
  try {
    storage.setItem(PLAN_KEY, hash);
  } catch {
    // Storage full or refused (a private window): the plan is lost, as before.
  }
}

/** Drop the kept plan, if any. */
export function forgetPlan(storage: StorageLike | null): void {
  try {
    storage?.removeItem(PLAN_KEY);
  } catch {
    // Storage refused: nothing was kept.
  }
}

/**
 * Whether a click on a link is a plain one that navigates this tab. A modified click
 * (Ctrl, Cmd, Shift, Alt) or a non-primary button opens another tab or window and leaves
 * this one on the plan, so nothing is kept for it (the accessibility re-check's note).
 */
export function isPlainClick(e: { button: number; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean }): boolean {
  return e.button === 0 && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey;
}

/**
 * Whether the sign-in round trip skips keeping a plan that holds the rider's
 * location ("Use my location", OWNER-DECISIONS 395). For now it does not: such
 * a plan is kept like any other, in this tab's sessionStorage only for the
 * round trip, and read once (and removed) on the next load; nothing is sent to
 * the server. This is the one documented place a location-derived point is
 * stored: the owner's accepted exception to "never stored" (OWNER-DECISIONS
 * 398, "yes, keep location"), so it stays false.
 *
 * The stress page link keeps a plan the same way (`rememberPlanForPage`, below), so
 * flipping this to true also needs that link to learn whether the plan holds a
 * location.
 *
 * Flipping it to true (the rider then comes back from sign-in to an empty plan)
 * also needs: the Settings sheet's sign-in sentence in App.tsx ("your current
 * plan is kept across the sign-in.") made true for a plan with a location, and
 * the two tests that pin false (signIn.test.ts and geolocation.test.ts's
 * never-stored test) changed with it. After a reload the in-memory flag is
 * gone, so a later sign-in keeps that plan even then; its hash is already in
 * the address bar by that point.
 */
export const SKIP_SIGN_IN_PLAN_WITH_LOCATION = false;

/** The sign-in link's handler: keep the plan for the round trip, unless it holds a location and that is skipped. */
export function rememberPlanForSignIn(
  storage: StorageLike | null,
  hash: string,
  holdsLocation: boolean,
  skipWithLocation: boolean = SKIP_SIGN_IN_PLAN_WITH_LOCATION,
): void {
  if (holdsLocation && skipWithLocation) return;
  rememberPlan(storage, hash);
}

/** This tab's sessionStorage, or null where the browser refuses it (a private window, a sandbox). */
export function tabSession(): StorageLike | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

/**
 * The stress page link's handler (`StressPageLink`, stressLegend.ts; the accessibility
 * review's SF1). /about/stress.html is a static page in the same tab, and its "Back to the
 * map" links go to a bare "/", which loses the fragment the plan lives in. So the plan is
 * kept as for the sign-in round trip: in this tab's sessionStorage, read once by
 * `planToOpen` on the next load that has no plan of its own. The browser's Back button
 * brings the fragment back itself: on a reload the page's own plan wins and the kept one is
 * dropped, and on a bfcache restore App drops it at `pageshow`.
 */
export function rememberPlanForPage(storage: StorageLike | null, hash: string): void {
  rememberPlan(storage, hash);
}

/**
 * The hash to open with: the page's own if it has a plan, else a remembered one (used once).
 *
 * A hash with points (`p=`) or only a ride type (`preset=`, which is what a
 * preset link such as /trailmaxxing redirects to) is the page's own plan: the
 * person followed that link on purpose, so it beats a plan left behind by a
 * sign-in that never came back. The callback itself lands on a bare "/".
 */
export function planToOpen(storage: StorageLike | null, hash: string): string {
  if (!storage) return hash;
  let saved: string | null = null;
  try {
    saved = storage.getItem(PLAN_KEY);
    storage.removeItem(PLAN_KEY);
  } catch {
    return hash;
  }
  if (/[#&](p|preset)=/.test(hash) || !saved) return hash;
  return saved;
}
