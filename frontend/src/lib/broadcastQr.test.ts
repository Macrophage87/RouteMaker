// Broadcast by QR code (Stephen 2026-10-26: "Also offer the ability to broadcast a route from a QR code. A long press
// would show a popup with the QR code"; "if you press and share multiple times in the same ride, it's the same link";
// "Also allow participants to share that same code as well").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { QR_MARGIN, qrPath } from "./broadcastQr.ts";

const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
const panel = readFileSync(new URL("../app/RoutePanel.tsx", import.meta.url), "utf8");
const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
const roam = readFileSync(new URL("../RoamMode.tsx", import.meta.url), "utf8");
const hold = readFileSync(new URL("./useHold.ts", import.meta.url), "utf8");

test("qrPath: one square path with its 4-module quiet zone, for a ride link with its plan", () => {
  const link = "https://example.org/s/0123456789abcdef0123456789abcdef#p=-77.04000,38.91000;-77.01000,38.89000;-76.61000,39.29000&preset=default&v=2&stress=70&hills=0&route=0123456789abcdef0123456789abcdef&ride=1&lead=0123456789abcdef0123456789abcdef";
  const { size, d } = qrPath(link);
  assert.ok(size >= 21 + QR_MARGIN * 2);
  assert.equal((size - QR_MARGIN * 2 - 17) % 4, 0, "a QR code is 17 + 4 x version modules wide");
  assert.match(d, /^(M\d+ \d+h1v1h-1z)+$/);
  // No module in the quiet zone.
  for (const [, x, y] of d.matchAll(/M(\d+) (\d+)/g)) {
    assert.ok(+x >= QR_MARGIN && +x < size - QR_MARGIN && +y >= QR_MARGIN && +y < size - QR_MARGIN);
  }
  assert.deepEqual(qrPath(link), { size, d }, "the same link, the same code");
});

test("a hold (a press held, a right-click, the menu key) shows the code, and the held press's click does nothing", () => {
  assert.match(hold, /if \(event\.button === 0\) timer\.current = window\.setTimeout\(fire, ms\);/);
  assert.match(hold, /onContextMenu: \(event\) => \{\s*event\.preventDefault\(\);\s*fire\(\);/);
  assert.match(hold, /onClickCapture: \(event\) => \{\s*if \(!held\.current\) return;\s*held\.current = false;\s*event\.preventDefault\(\);\s*event\.stopPropagation\(\);/);
  // Beside Start, on the ride screen and in Roam, each said to screen readers.
  assert.match(panel, /onClick=\{ride\.onBroadcast\} \{\.\.\.broadcastHold\}/);
  assert.match(panel, /\{BROADCAST_ABOUT\} \{BROADCAST_HOLD_HINT\}/);
  for (const page of [ride, roam]) {
    assert.match(page, /onClick=\{\(\) => void broadcast\(\)\}\s*\{\.\.\.broadcastHold\}\s*aria-describedby=\{onBroadcastHold \? broadcastHoldId : undefined\}/);
    assert.match(page, /\{BROADCAST_HOLD_HINT\}/);
  }
  assert.match(app, /broadcastRide: \{ onPress: broadcastRide, onHold: broadcastQr, note: broadcastNote \}/);
  assert.match(app, /const rideCanBroadcast = !!rideStart && !rideStart\.roam && \(rideStart\.route === shown \|\| \(rideStart\.kept === true && !rideStart\.others\)\) && \(!\(onShared && !onShared\.own\) \|\| passesOn\);/);
  assert.match(app, /onBroadcastHold=\{rideCanBroadcast \? broadcastQrFromRide : null\}/);
  assert.match(app, /onBroadcastHold=\{roamKeyless \? null : broadcastRoamQr\}/);
  assert.match(app, /<BroadcastQrDialog ask=\{qrAsk\} onClose=\{\(\) => setQrAsk\(null\)\} \/>/);
});

test("the code's link is Broadcast's own, made by the same shareRoute; Start ride only beside Start before the ride", () => {
  assert.match(app, /const start = riding \? null : \(\) => startRideNoted\(""\);/);
  assert.match(app, /void shareRoute\(true, keepsLink\(got\)\)\.then\(\(\{ led, said \}\) => \{\s*if \(led && got\.url\) setQrAsk\(\{ link: got\.url, start \}\);/);
  assert.match(app, /const \{ led, said \} = await shareRoute\(true, keepsLink\(got\)\);/);
  assert.match(app, /const said = await broadcastRoam\(keepsLink\(got\)\);/);
});

test("one link per ride: shared again for the route ridden, the link sent before, with its leader key", () => {
  assert.match(app, /const rideRoute = riding && rideStart \? rideStart\.route : sharedRoute;\s*const again = ride && rideLinkSent\.current\?\.route === rideRoute && rideLinkSent\.current\.keep === shareKeep \? rideLinkSent\.current : null;/);
  assert.match(app, /if \(led\) rideLinkSent\.current = \{ route: rideRoute, keep: shareKeep, link, lead, id: sharedId \};/);
});

test("one following passes on the link they opened, by the sheet or the code; their leader stays the leader", () => {
  assert.match(app, /const SHARED_LINK = SHARED_RIDE && SHARED_LEAD \? passedOnLink\(window\.location\) : null;\nif \(SHARED_ID && /);
  assert.match(app, /const followedLink = \(\) => \(SHARED_LINK && sharedOpenNow\.current\?\.lead && !sharedOpenNow\.current\.own && sharedOpenNow\.current\.id === SHARED_ID \? SHARED_LINK : null\);/);
  assert.match(app, /if \(followed\) return setQrAsk\(\{ link: followed, start \}\);/);
  assert.match(app, /if \(roamBroadcast && !roamBroadcast\.leading\) \{\s*\/\/[^\n]*\n\s*if \(roamKeyless\) return BROADCAST_NO_KEY;\s*const done = await shareLink\(nav, \{ title: ROAM_BROADCAST_TITLE, text: ROAM_BROADCAST_TEXT, url: roamLink\(window\.location\.origin, roamBroadcast\.id, roamBroadcast\.lead, roamBroadcast\.secret\) \}\);/);
  assert.match(ride, /passingOn \? t\("\{name\}: pass on the link to this ride", \{ name: RIDE_BROADCAST_NAME \}\)/);
});

test("the review's guards: a link turned off, another keeping or a ride ended is not sent again; asked on a computer", () => {
  assert.match(app, /if \(rodeBefore\.current && !riding\) \{\s*rideLinkSent\.current = null;/);
  // Nor its lead or the page's Group Ride secret: the next ride is a new ride under a new token and secret.
  assert.match(app, /if \(!id\.startsWith\("roam\|"\)\) leads\.current\.delete\(id\);/);
  assert.match(app, /if \(groupSecretOwn\.current\) setGroupSecret\(newRideSecret\(\)\);/);
  assert.match(app, /setGroupSecret\(newRideSecret\(\)\);\s*\/\/[^\n]*\n\s*forgetAnsweredHere\(\);/);
  assert.match(app, /if \(!riding && !computerOk\.current && askBeforeStart\(looksLikePhone\(\), tabSession\(\)\)\) \{\s*setComputerAsk\("qr"\);/);
  // Only a broadcast whose link this page opened is passed on; any other ride opened from a link has no Broadcast.
  assert.match(app, /const passesOn =\s*onShared !== null && !onShared\.own && !!onShared\.lead && SHARED_LINK !== null && onShared\.id === SHARED_ID && !followsWithoutKey\(/);
  // A messaging app's tracking parameters are not passed on.
  assert.match(app, /for \(const name of \["route", RIDE_PARAM, LEAD_PARAM\]\) \{/);
});

test("a resumed ride keeps Share live, its link made from the ride's own plan (Stephen 2026-10-29)", () => {
  // A ride resumed after the page closed, or one whose plan was made again since Start, no longer has the plan shown
  // as its route: Share live stays, sharing the ride itself, not whatever the plan now shows.
  assert.match(app, /const rideOwnShare = \(\) => \(riding && rideStart\?\.kept && !rideStart\.others && rideStart\.route !== shown \? rideStart : null\);/);
  assert.match(app, /const shareExact = \(\) => \{\s*const ride = rideOwnShare\(\);\s*if \(ride\) \{[\s\S]*?of: ride\.route,\s*save: planSave\(name, ride\.route, ride\.points, ride\.preset, ride\.dials\),/);
  assert.match(app, /const from = rideOwnShare\(\) \?\? \{ points, preset, dials \};\s*let link = withSecret\(linkToCopy\(window\.location, from\.points, from\.preset, from\.dials,/);
  assert.match(app, /const ownRide = rideOwnShare\(\);\s*const sharedRoute = ownRide\?\.route \?\? shown;\s*if \(!sharedRoute \|\| sharing\.current\)/);
  // Someone else's ride stays theirs once resumed: kept with it, and no Share live of the rider's own.
  assert.match(app, /const others = opened !== null && !opened\.own;/);
  assert.match(app, /keepLeftRide\(\{ route, points: leg\.points, loop: leg\.loop, preset: leg\.preset, dials: rideDialsNow, fixed, destination, others \}/);
  // Resume keeps the ride kept, so the rail still offers it.
  assert.match(app, /setRideStart\(\(before\) => \(\{ \.\.\.left, trip: null, kept: true, n: \(before\?\.n \?\? 0\) \+ 1 \}\)\);/);
});
