// "Share" (owner, 2026-10-10; PLAN.md FOLLOWUP): the phone's share sheet for the same link "Copy link"
// copies (sidebar.ts linkToCopy): this page with encodePlan's fragment at full precision, never the weight
// (OWNER-DECISIONS 313). The button is on the page only where the browser has a share sheet, so Copy link
// is always there. The location line (OWNER-DECISIONS 395) describes the button, so it is read before
// the sheet opens; the shared text holds the distance and the ride type, nothing private.
//
// v0.7.0, "share the identical route" (lib/sharedRoutes.ts): the link also names the exact line shown, kept on
// the server, so it opens unchanged; and where the browser can share files, the sheet also carries the GPX file
// Download GPX would save (withGpxFile).
import { formatDistance } from "./format.ts";

/** The button's visible word and its accessible name (the name holds the word: WCAG 2.5.3). */
export const SHARE_LABEL = "Share route";
export const SHARE_NAME = "Share route";
/** Share ride (lib/sharedRoutes.ts RIDE_PARAM): the same link, ridden fixed, with location sharing offered. */
export const SHARE_RIDE_LABEL = "Share ride";
/** Beside Start (Stephen 2026-10-22): Share ride's link, led by the sharer, then the ride. */
export const BROADCAST_LABEL = "Broadcast";
export const BROADCAST_ABOUT = "Broadcast: send a link and start the ride. You lead: those who open it follow your dot and the path you take.";
export const SHARE_TITLE = "RouteMaker route";
export const SHARE_FAILED = "Could not open the share sheet. Use Copy link instead.";

/** What Share hands the sheet. */
export interface ShareContent {
  title: string;
  text: string;
  url: string;
  /** The route's GPX file, where the browser can share files (withGpxFile). */
  files?: File[];
}

/** The part of `navigator` Share uses. */
export interface ShareNavigator {
  share?: (data: ShareContent) => Promise<void>;
  canShare?: (data: { url?: string; files?: File[] }) => boolean;
}

/**
 * The share sheet to use (Stephen 2026-10-26: "I don't seem to be able to broadcast rides", in the phone app): the
 * browser's where it has one; else the phone app's own (lib/nativeShell.ts nativeShareNavigator), since Android's
 * WebView has no navigator.share; else none.
 */
export function pickShareNavigator(nav: ShareNavigator | undefined, native: ShareNavigator | null): ShareNavigator | undefined {
  return typeof nav?.share === "function" ? nav : (native ?? nav);
}

/** Broadcast where there is no share sheet at all (an older phone app, most computers): the link is copied. */
export const BROADCAST_COPIED = "Broadcast link copied. Paste it to your riders: they follow you once they open it.";
/** The copy failed: beside Plan's and Go's Broadcast (nothing started), and on the ride and Roam screens. */
export const BROADCAST_COPY_FAILED = "Could not copy the link, so the ride did not start.";
export const BROADCAST_RIDE_COPY_FAILED = "Could not copy the link. Press Broadcast to try again.";

/**
 * Broadcast's stand-in for a share sheet: "sharing" copies the link (`copy`, Copy link's own method). It is called
 * inside the press, as a sheet is, so the clipboard is written while the press's activation holds. A copy that fails
 * is a failure ("CopyFailed"), so nothing starts.
 */
export function copyShareNavigator(copy: (text: string) => Promise<boolean>): ShareNavigator {
  return {
    share: (data) =>
      copy(data.url).then((done) => {
        if (!done) throw Object.assign(new Error("The link could not be copied"), { name: "CopyFailed" });
      }),
  };
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

/**
 * The shared text: "4.7 mi (7.6 km) bike route. Ride type: Group Ride." The distance is the route shown,
 * so it is left out (null) while that route is not the plan's points the link carries (a re-plan pending):
 * "Bike route. Ride type: Group Ride."
 */
export function shareText(distanceM: number | null, rideType: string): string {
  const what = distanceM === null ? "Bike route" : `${formatDistance(distanceM)} bike route`;
  return `${what}. Ride type: ${rideType}.`;
}

/** The sheet's content: `url` is Copy link's link, unchanged. */
export function shareContent(url: string, distanceM: number | null, rideType: string): ShareContent {
  return { title: SHARE_TITLE, text: shareText(distanceM, rideType), url };
}

/**
 * The content with the GPX file added, where the browser says it can share that file (Web Share level 2, on
 * phones mostly); otherwise the content as it was, the link alone. A browser that cannot say is not given it.
 */
export function withGpxFile(nav: ShareNavigator | undefined, content: ShareContent, file: File | null): ShareContent {
  if (!file || typeof nav?.canShare !== "function") return content;
  try {
    return nav.canShare({ files: [file] }) === true ? { ...content, files: [file] } : content;
  } catch {
    return content;
  }
}

export type ShareOutcome = "shared" | "cancelled" | "failed";

/** Errors that are not failures to tell the rider about: the sheet closed, or one is already open. */
const SILENT_ERRORS = new Set(["AbortError", "InvalidStateError"]);

/**
 * Opens the sheet. `nav.share` is called synchronously, before this function's first await, so the
 * press's user activation still holds (browsers refuse share() without it, NotAllowedError); callers
 * must call this before any await of their own. The rider closing the sheet (AbortError), or a second
 * press while one is open (InvalidStateError), is "cancelled"; any other failure is "failed".
 */
export function shareLink(nav: ShareNavigator | undefined, content: ShareContent): Promise<ShareOutcome> {
  if (typeof nav?.share !== "function") return Promise.resolve("failed");
  let pending: Promise<void>;
  try {
    pending = nav.share(content);
  } catch (error) {
    pending = Promise.reject(error);
  }
  return Promise.resolve(pending).then(
    (): ShareOutcome => "shared",
    (error): ShareOutcome => {
      const name = (error as { name?: unknown } | null)?.name;
      return typeof name === "string" && SILENT_ERRORS.has(name) ? "cancelled" : "failed";
    },
  );
}

/**
 * What the page says after Share: nothing when the sheet opened (the browser does not say where the link
 * went, so "Shared" could be untrue) or the rider closed it; a failure is said, with Copy link offered.
 */
export function shareSaidFor(outcome: ShareOutcome): string {
  return outcome === "failed" ? SHARE_FAILED : "";
}
