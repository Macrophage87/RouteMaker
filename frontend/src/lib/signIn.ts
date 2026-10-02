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
