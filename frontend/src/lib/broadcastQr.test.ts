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
  assert.match(app, /const rideCanBroadcast = !!rideStart && !rideStart\.roam && rideStart\.route === shown && \(!\(onShared && !onShared\.own\) \|\| passesOn\);/);
  assert.match(app, /onBroadcastHold=\{rideCanBroadcast \? broadcastQrFromRide : null\}/);
  assert.match(app, /onBroadcastHold=\{broadcastRoamQr\}/);
  assert.match(app, /<BroadcastQrDialog ask=\{qrAsk\} onClose=\{\(\) => setQrAsk\(null\)\} \/>/);
});

test("the code's link is Broadcast's own, made by the same shareRoute; Start ride only beside Start before the ride", () => {
  assert.match(app, /const start = riding \? null : \(\) => startRideNoted\(""\);/);
  assert.match(app, /void shareRoute\(true, keepsLink\(got\)\)\.then\(\(\{ led, said \}\) => \{\s*if \(led && got\.url\) setQrAsk\(\{ link: got\.url, start \}\);/);
  assert.match(app, /const \{ led, said \} = await shareRoute\(true, keepsLink\(got\)\);/);
  assert.match(app, /const said = await broadcastRoam\(keepsLink\(got\)\);/);
});

test("one link per ride: shared again for the route ridden, the link sent before, with its leader key", () => {
  assert.match(app, /const rideRoute = riding && rideStart \? rideStart\.route : shown;\s*const again = ride && rideLinkSent\.current\?\.route === rideRoute && rideLinkSent\.current\.keep === shareKeep \? rideLinkSent\.current : null;/);
  assert.match(app, /if \(led\) rideLinkSent\.current = \{ route: rideRoute, keep: shareKeep, link, lead, id: sharedId \};/);
});

test("one following passes on the link they opened, by the sheet or the code; their leader stays the leader", () => {
  assert.match(app, /const SHARED_LINK = SHARED_RIDE && SHARED_LEAD \? passedOnLink\(window\.location\) : null;\nif \(SHARED_ID && /);
  assert.match(app, /const followedLink = \(\) => \(SHARED_LINK && sharedOpenNow\.current\?\.lead && !sharedOpenNow\.current\.own && sharedOpenNow\.current\.id === SHARED_ID \? SHARED_LINK : null\);/);
  assert.match(app, /if \(followed\) return setQrAsk\(\{ link: followed, start \}\);/);
  assert.match(app, /if \(roamBroadcast && !roamBroadcast\.leading\) \{\s*const done = await shareLink\(nav, \{ title: ROAM_BROADCAST_TITLE, text: ROAM_BROADCAST_TEXT, url: roamLink\(window\.location\.origin, roamBroadcast\.id, roamBroadcast\.lead, roamBroadcast\.secret\) \}\);/);
  assert.match(ride, /passingOn \? t\("\{name\}: pass on the link to this ride", \{ name: RIDE_BROADCAST_NAME \}\)/);
});

test("the review's guards: a link turned off, another keeping or a ride ended is not sent again; asked on a computer", () => {
  assert.match(app, /if \(rodeBefore\.current && !riding\) rideLinkSent\.current = null;/);
  assert.match(app, /if \(!riding && !computerOk\.current && askBeforeStart\(looksLikePhone\(\), tabSession\(\)\)\) \{\s*setComputerAsk\("qr"\);/);
  // Only a broadcast whose link this page opened is passed on; any other ride opened from a link has no Broadcast.
  assert.match(app, /const passesOn = onShared !== null && !onShared\.own && !!onShared\.lead && SHARED_LINK !== null && onShared\.id === SHARED_ID;/);
  // A messaging app's tracking parameters are not passed on.
  assert.match(app, /for \(const name of \["route", RIDE_PARAM, LEAD_PARAM\]\) \{/);
});
