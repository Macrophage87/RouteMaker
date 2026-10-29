// Share (owner, 2026-10-10): the phone's share sheet for Copy link's link. App.tsx is not rendered by a
// test, so its wiring is read as source, as sidebar.test.ts does for Copy link.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { startDials, type Dials } from "./dials.ts";
import { encodePlan } from "./planHash.ts";
import { linkToCopy } from "./sidebar.ts";
import {
  BROADCAST_COPIED,
  SHARE_FAILED,
  copyShareNavigator,
  pickShareNavigator,
  SHARE_LABEL,
  SHARE_NAME,
  SHARE_TITLE,
  canShareLink,
  shareContent,
  shareLink,
  shareSaidFor,
  shareText,
  type ShareContent,
} from "./share.ts";
import { appSource } from "../testSupport/appSource.mjs";

const app = appSource();
const noop = async () => {};

test("Share shows only where the browser has navigator.share and, if it can say, can share a link", () => {
  assert.equal(canShareLink(undefined, "https://x.test/"), false);
  assert.equal(canShareLink({}, "https://x.test/"), false);
  assert.equal(canShareLink({ share: noop }, "https://x.test/"), true);
  assert.equal(canShareLink({ share: noop, canShare: () => true }, "https://x.test/"), true);
  assert.equal(canShareLink({ share: noop, canShare: () => false }, "https://x.test/"), false);
  assert.equal(
    canShareLink({ share: noop, canShare: () => { throw new TypeError("no"); } }, "https://x.test/"),
    false,
  );
  const asked: unknown[] = [];
  canShareLink({ share: noop, canShare: (d) => (asked.push(d), true) }, "https://x.test/#p=1");
  assert.deepEqual(asked, [{ url: "https://x.test/#p=1" }]);
});

test("the shared text is the distance, US first with metric in brackets, and the ride type; nothing else", () => {
  assert.equal(shareText(7563, "Group Ride"), "4.7 mi (7.6 km) bike route. Ride type: Group Ride.");
  const content = shareContent("https://x.test/#p", 7563, "Default");
  assert.deepEqual(Object.keys(content).sort(), ["text", "title", "url"]);
  assert.equal(content.title, SHARE_TITLE);
  assert.equal(SHARE_TITLE, "RouteMaker route");
  // No distance while a re-plan is pending: the route shown is not the points the link carries.
  assert.equal(shareText(null, "Mass Ride"), "Bike route. Ride type: Mass Ride.");
  assert.match(app, /const distanceM = !stale && routedPoints === points \? shown\.distance_m : null;/);
});

test("the shared URL is Copy link's, at its full precision and without the weight", async () => {
  const points: Array<[number, number]> = [
    [-77.0312345, 38.9012345],
    [-77.0598765, 38.9234567],
  ];
  const dials: Dials = { ...startDials("default"), systemWeightKg: 97.5 };
  const where = { origin: "https://x.test", pathname: "/", search: "" };
  const url = linkToCopy(where, points, "default", dials);
  const sent: ShareContent[] = [];
  const outcome = await shareLink({ share: async (d) => void sent.push(d) }, shareContent(url, 5000, "Default"));
  assert.equal(outcome, "shared");
  assert.equal(sent.length, 1);
  assert.equal(sent[0].url, url);
  assert.equal(sent[0].url, `https://x.test/${encodePlan(points, "default", dials)}`);
  assert.doesNotMatch(`${sent[0].url} ${sent[0].text}`, /weight|97\.5|\bkg\b|\blbs?\b/i);
  // App hands share the link Copy link copies, with only the shared line's id added (lib/sharedRoutes.ts).
  assert.match(app, /let link = withSecret\(linkToCopy\(window\.location, points, preset, dials, viaIndices\(points, VIA_MARKS\.isVia\)\), isRideLinkType\(preset\) \? groupSecret : null\);/);
  assert.match(app, /link = withSharedId\(link, id\);/);
  assert.match(app, /shareContent\(link, distanceM, presetSaid\(preset\)\)/);
  // Copy link copies that same link, the exact line's id and all (v0.9.0, "share the exact route").
  assert.match(app, /const \{ link, kept \} = sharedLinkNow\(\);\s*const done = await copyText\(link, navigator\.clipboard, selectionCopy\);/);
});

test("the rider closing the sheet is silent; any other failure says so and offers Copy link", async () => {
  const content = shareContent("https://x.test/", 1000, "Default");
  const abort = Object.assign(new Error("cancelled"), { name: "AbortError" });
  assert.equal(await shareLink({ share: () => Promise.reject(abort) }, content), "cancelled");
  assert.equal(await shareLink({ share: () => Promise.reject(new DOMException("x", "AbortError")) }, content), "cancelled");
  assert.equal(await shareLink({ share: () => Promise.reject(new DOMException("x", "NotAllowedError")) }, content), "failed");
  assert.equal(await shareLink({ share: () => Promise.reject(null) }, content), "failed");
  // A second press while a sheet is open: the browser's InvalidStateError is not a failure to announce.
  assert.equal(await shareLink({ share: () => Promise.reject(new DOMException("x", "InvalidStateError")) }, content), "cancelled");
  assert.equal(await shareLink({ share: () => { throw new DOMException("x", "DataError"); } }, content), "failed");
  assert.equal(await shareLink({}, content), "failed");
  assert.equal(shareSaidFor("shared"), "");
  assert.equal(shareSaidFor("cancelled"), "");
  assert.equal(shareSaidFor("failed"), SHARE_FAILED);
  assert.match(SHARE_FAILED, /Copy link/);
});

test("App shows Share beside Copy link only where it is supported, named Share route, described by the location line", () => {
  assert.equal(SHARE_LABEL, "Share route");
  assert.equal(SHARE_NAME, "Share route");
  assert.ok(SHARE_NAME.startsWith(SHARE_LABEL), "the accessible name holds the visible word");
  assert.match(app, /const \[shareNav\] = useState\(\(\) => pickShareNavigator\(navigator, nativeShareNavigator\(\)\)\);/);
  assert.match(app, /const \[canShare\] = useState\(\(\) => canShareLink\(shareNav, window\.location\.href\)\);/);
  // The owner, 2026-10-17 ("the share button should be in files. Basically you save then you share"): in the Route
  // file sheet, Save route first, then Share and its keeping; Plan's More keeps Share as image, not Share.
  const controls = app.slice(app.indexOf("export function ShareControls"), app.indexOf("function RouteActions("));
  assert.match(
    controls,
    /\{save\}\s*\{canShare && ready && \(\s*<div className="share-buttons">\s*<button\s*type="button"\s*className="secondary share-route"\s*onClick=\{\(\) => shareRoute\(false\)\}\s*aria-describedby=\{`share-route-about\$\{note\}`\}/,
  );
  assert.match(controls, /\{canShare && ready && linkNote && \(\s*<p id="share-link-note" className="hint link-note">/);
  assert.match(controls, /\{canShare && ready && onShareKeep && <ShareKeepField value=\{shareKeep\} onChange=\{onShareKeep\} \/>\}/);
  const more = app.slice(app.indexOf('<div id={moreId} className="route-more-body"'), app.indexOf("</div>", app.indexOf('<div id={moreId} className="route-more-body"')));
  assert.doesNotMatch(more, /share-route|SaveRoute/);
  assert.match(more, /className="secondary share-image" onClick=\{shareImage\} aria-haspopup="dialog"/);
  const appFile = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(appFile, /<ShareControls\s*save=\{saveProps \? <SaveRoute \{\.\.\.saveProps\} label=\{SAVE_ROUTE\} \/> : null\}\s*canShare=\{canShare\}\s*ready=\{!!shown\}/);
  // A failure is said in the sheet's polite status beside Share, and shown; success and cancel say nothing.
  assert.match(app, /const done = await outcome;\s*said = shareSaidFor\(done\);/);
  assert.match(app, /if \(said\)\s*window\.setTimeout/);
  assert.match(app, /if \(press === sharePresses\.current\) setShareSaid\(\(before\) => \(\{ text: said, count: before\.count \+ 1 \}\)\);/);
  assert.match(controls, /<p className="hint share-said" role="status">/);
});

test("share() is called within the press: synchronously in shareLink, and before any await in shareRoute", () => {
  // shareLink calls navigator.share before it returns, not after a tick.
  let called = false;
  void shareLink({ share: async () => void (called = true) }, shareContent("https://x.test/", 1, "Default"));
  assert.equal(called, true, "share() called synchronously");
  // App's handler: no await before shareLink(...), and a press while a sheet is open is skipped.
  const start = app.indexOf("const shareRoute = async (ride = false, nav: ShareNavigator | undefined = shareNav): Promise<{ led: boolean; said: string }> => {");
  assert.ok(start > 0);
  const body = app.slice(start, app.indexOf("\n  };\n", start));
  const call = body.indexOf("shareLink(nav, content)");
  assert.ok(call > 0, "shareRoute calls shareLink");
  assert.doesNotMatch(body.slice(0, call).replace(/\/\/[^\n]*/g, ""), /\bawait\b/, "no await before shareLink");
  assert.match(body, /if \(!shown \|\| sharing\.current\) return \{ led: false, said: "" \};/);
  assert.match(body, /return \{ led: false, said: SHARE_RIDE_WAIT \};\s*\}\s*sharing\.current = true;/);
  assert.match(body, /finally \{\s*sharing\.current = false;\s*\}/);
});

test("the share sheet: the browser's where it has one, else the phone app's (Android's WebView has none), else none", () => {
  const browser = { share: noop };
  const native = { share: noop };
  assert.equal(pickShareNavigator(browser, native), browser);
  assert.equal(pickShareNavigator({}, native), native);
  assert.equal(pickShareNavigator(undefined, native), native);
  const none = {};
  assert.equal(pickShareNavigator(none, null), none);
  assert.equal(canShareLink(pickShareNavigator({}, null), "https://x.test/"), false);
  assert.equal(canShareLink(pickShareNavigator({}, native), "https://x.test/"), true);
});

test("Broadcast with no share sheet copies the link, inside the press; a failed copy is a failure, so nothing starts", async () => {
  const copied: string[] = [];
  const nav = copyShareNavigator(async (text) => (copied.push(text), true));
  const outcome = shareLink(nav, shareContent("https://x.test/#p=1&ride=1", 1, "Default"));
  assert.deepEqual(copied, ["https://x.test/#p=1&ride=1"], "copied synchronously, while the press's activation holds");
  assert.equal(await outcome, "shared");
  assert.equal(await shareLink(copyShareNavigator(async () => false), shareContent("https://x.test/", 1, "Default")), "failed");
  assert.match(BROADCAST_COPIED, /^Live link copied\. Paste it to your riders/);
});

test("App: Broadcast shows everywhere; with no share sheet it copies, and the ride screen, Ride and Roam say so", () => {
  assert.ok(app.includes("const broadcastNav = useMemo<ShareNavigator | undefined>(() => (canShare ? shareNav : copyShareNavigator((text) => copyText(text, navigator.clipboard, selectionCopy))), [canShare, shareNav]);"));
  assert.match(app, /if \(led\) return canShare \? ROAM_BROADCAST_ON : BROADCAST_COPIED;/);
  assert.match(app, /return canShare \? ROAM_BROADCAST_ON : BROADCAST_COPIED;\n  \};/);
  // Roam pressed again while leading: a copy is said (a sheet is its own answer).
  assert.match(app, /if \(mine\) return canShare \? "" : BROADCAST_COPIED;/);
  // A failed copy says so, not "share sheet".
  assert.match(app, /said === SHARE_FAILED \? \(canShare \? BROADCAST_SHARE_FAILED : BROADCAST_COPY_FAILED\) : said/);
  assert.match(app, /said === SHARE_FAILED \? \(canShare \? BROADCAST_RIDE_FAILED : BROADCAST_RIDE_COPY_FAILED\) : said/);
  // Each Start ride press sets the note (plain Start: none), and Go back or Reroute at a closure drops it, so a later
  // ride never says a copy it did not make.
  assert.match(app, /const startRideChecked = \(\) => startRideNoted\(""\);/);
  assert.match(app, /const startRideNoted = \(note: string\) => \{\s*rideNote\.current = note;/);
  assert.match(app, /const closureCancel = \(\) => \{\s*closurePending\.current = null;\s*rideNote\.current = "";/);
  assert.match(app, /const closureReroute = async \(\) => \{\s*const pending = closurePending\.current;\s*closurePending\.current = null;\s*rideNote\.current = "";/);
  assert.equal((app.match(/rideNote\.current = /g) ?? []).length, 4, "set only by a press, and cleared where no ride starts or one does");
  // The note is taken once by the next ride and handed to the ride screen.
  assert.match(app, /const note = rideNote\.current;\s*rideNote\.current = "";\s*setRideStart\(\(before\) => \(\{[^\n]*note, n:/);
  assert.match(app, /startNote=\{rideStart\.note\}/);
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /const startNoteRef = useRef\(startNote\);\s*useEffect\(\(\) => \{\s*const text = startNoteRef\.current;\s*if \(!text\) return;\s*const timer = window\.setTimeout\(\(\) => answer\(text\), START_NOTE_MS\);/);
});
