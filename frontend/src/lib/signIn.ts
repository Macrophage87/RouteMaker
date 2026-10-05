/**
 * Keeping a signed-out plan across the Discord sign-in round trip.
 *
 * /auth/login goes to Discord and the callback lands on "/", which loses the
 * URL fragment the plan lives in. The plan is not put in a `next` parameter:
 * that would send the points to our server's logs and to Discord. It goes in
 * this tab's sessionStorage just before the link is followed, and is read back
 * once, on a load that has no plan of its own.
 */
export const PLAN_KEY = "routemaker.plan-before-sign-in";

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export function rememberPlan(storage: StorageLike | null, hash: string): void {
  if (!storage || !/[#&]p=/.test(hash)) return;
  try {
    storage.setItem(PLAN_KEY, hash);
  } catch {
    // Storage full or refused (a private window): the plan is lost, as before.
  }
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
