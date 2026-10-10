// "Share" (owner, 2026-10-10; PLAN.md FOLLOWUP): the phone's share sheet for the same link "Copy link"
// copies (sidebar.ts linkToCopy): this page with encodePlan's fragment at full precision, never the weight
// (OWNER-DECISIONS 313). The button is on the page only where the browser has a share sheet, so Copy link
// is always there. The location line (OWNER-DECISIONS 395) describes the button, so it is read before
// the sheet opens; the shared text holds the distance and the ride type, nothing private.
import { formatDistance } from "./format.ts";

/** The button's visible word and its accessible name (the name holds the word: WCAG 2.5.3). */
export const SHARE_LABEL = "Share";
export const SHARE_NAME = "Share route";
export const SHARE_TITLE = "RouteMaker route";
export const SHARE_FAILED = "Could not open the share sheet. Use Copy link instead.";

/** What Share hands the sheet. */
export interface ShareContent {
  title: string;
  text: string;
  url: string;
}

/** The part of `navigator` Share uses. */
export interface ShareNavigator {
  share?: (data: ShareContent) => Promise<void>;
  canShare?: (data: { url: string }) => boolean;
}

/** Whether to show Share: the browser has navigator.share and, where it can say, can share a link. */
export function canShareLink(nav: ShareNavigator | undefined, url: string): boolean {
  if (typeof nav?.share !== "function") return false;
  if (typeof nav.canShare !== "function") return true;
  try {
    return nav.canShare({ url }) === true;
  } catch {
    return false;
  }
}

/** The shared text: "4.7 mi (7.6 km) bike route. Ride type: Group Ride." */
export function shareText(distanceM: number, rideType: string): string {
  return `${formatDistance(distanceM)} bike route. Ride type: ${rideType}.`;
}

/** The sheet's content: `url` is Copy link's link, unchanged. */
export function shareContent(url: string, distanceM: number, rideType: string): ShareContent {
  return { title: SHARE_TITLE, text: shareText(distanceM, rideType), url };
}

export type ShareOutcome = "shared" | "cancelled" | "failed";

/** Opens the sheet. The rider closing it (AbortError) is "cancelled"; any other failure is "failed". */
export async function shareLink(nav: ShareNavigator | undefined, content: ShareContent): Promise<ShareOutcome> {
  if (typeof nav?.share !== "function") return "failed";
  try {
    await nav.share(content);
    return "shared";
  } catch (error) {
    return (error as { name?: unknown } | null)?.name === "AbortError" ? "cancelled" : "failed";
  }
}

/**
 * What the page says after Share: nothing when the sheet opened (the browser does not say where the link
 * went, so "Shared" could be untrue) or the rider closed it; a failure is said, with Copy link offered.
 */
export function shareSaidFor(outcome: ShareOutcome): string {
  return outcome === "failed" ? SHARE_FAILED : "";
}
