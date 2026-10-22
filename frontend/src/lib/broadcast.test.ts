// A broadcast ride (Stephen 2026-10-22: "allow both plan and go rides to be started as broadcasts where the ride
// leader is the person who shared. Opening the link will follow the leader and share the path"; "Have that as like a
// small button next to start"; "You then get a share screen and send it").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { LonLat } from "./geo.ts";
import {
  CONSENT_KEY,
  TRAIL_MAX_POINTS,
  broadcastRideId,
  consentFor,
  extendTrail,
  keepConsent,
  leadConsent,
  leaderKey,
  readRide,
  rideId,
  ridersSaid,
  shownDots,
} from "./rideGroup.ts";
import { asRideLink, leadKeyFrom, rideLinkFrom } from "./sharedRoutes.ts";
import { BROADCAST_LABEL } from "./share.ts";

const LINE: LonLat[] = Array.from({ length: 21 }, (_, i) => [-77.04 + i * 0.002, 38.9] as LonLat);
const KEY = "8a83665f3798727f14f92ad0e6c99fda";

class Memory {
  map = new Map<string, string>();
  getItem(key: string) {
    return this.map.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.map.set(key, value);
  }
}

const read = (file: string) => readFileSync(new URL(file, import.meta.url), "utf8");

test("the leader key is the server's: the first 32 hex digits of the SHA-256 of the sharer's token", async () => {
  // core.ride_presence.leader_key("1" * 32), worked out in Python.
  assert.equal(await leaderKey("1".repeat(32)), KEY);
  assert.notEqual(await leaderKey("2".repeat(32)), KEY);
});

test("a broadcast link carries the leader key beside ride=1, and only a well-formed key is read back", () => {
  const link = asRideLink("https://x.test/s/abc#p=1", KEY);
  assert.equal(link, `https://x.test/s/abc#p=1&ride=1&lead=${KEY}`);
  const hash = link.slice(link.indexOf("#"));
  assert.equal(rideLinkFrom(hash), true);
  assert.equal(leadKeyFrom(hash), KEY);
  assert.equal(leadKeyFrom("", `?route=x&ride=1&lead=${KEY}`), KEY, "the query sent on from /s/<id>");
  assert.equal(leadKeyFrom(`#lead=${KEY}`), null, "a leader only on a ride link");
  assert.equal(leadKeyFrom("#ride=1&lead=nothex"), null);
  // An older Share ride link, or one shared before the key was ready: a ride with no leader.
  assert.equal(asRideLink("https://x.test/#p=1"), "https://x.test/#p=1&ride=1");
  assert.equal(asRideLink("https://x.test/#p=1", "short"), "https://x.test/#p=1&ride=1");
});

test("a broadcast is its shared line's ride: the sharer and its openers are on it whatever each one rides", async () => {
  const a = await broadcastRideId("a".repeat(32));
  assert.match(a, /^[0-9a-f]{64}$/);
  assert.equal(a, await broadcastRideId("a".repeat(32)));
  assert.notEqual(a, await broadcastRideId("b".repeat(32)));
  assert.notEqual(a, await rideId("group-ride", LINE));
});

test("the sharer's answer: shown, as Lead line, under the token the link's key names, even after an earlier share", () => {
  const store = new Memory();
  const before = keepConsent("r", "no", 1000, store, "1".repeat(32), "sweep");
  assert.equal(before.token, "1".repeat(32));
  const led = leadConsent("r", "2".repeat(32), 2000, store);
  assert.deepEqual(led, { answer: "yes", token: "2".repeat(32), since: 1000, role: "lead" });
  assert.deepEqual(consentFor("r", 3000, store), led);
  assert.ok(store.getItem(CONSENT_KEY)?.includes("2".repeat(32)));
});

test("the leader is drawn off the route too (the sharer may re-route); the others only near it", () => {
  const off: LonLat = [-77.02, 38.92]; // about 1.4 mi (2.2 km) north of the line
  const shown = shownDots(LINE, [
    { lon: off[0], lat: off[1], age_s: 1, role: "lead", leader: true },
    { lon: off[0], lat: off[1], age_s: 1, role: "lead" },
    { lon: -77.03, lat: 38.9, age_s: 1 },
  ]);
  assert.equal(shown.length, 2);
  assert.equal(shown[0].leader, true);
  assert.equal(shown[1].leader, false);
});

test("on a broadcast every dot is drawn, on or off the route, so separated riders can find each other", () => {
  const off = { lon: -77.02, lat: 38.92, age_s: 1 };
  assert.equal(shownDots(LINE, [off]).length, 0);
  const shown = shownDots(LINE, [off], 0, { anywhere: true });
  assert.equal(shown.length, 1);
  assert.equal(shown[0].leader, false);
});

test("the riders line names the ride leader first, with or without the rider's own place", () => {
  const shown = shownDots(LINE, [
    { lon: -77.01, lat: 38.9, age_s: 5, role: "lead", leader: true },
    { lon: -77.035, lat: 38.9, age_s: 5 },
  ]);
  assert.match(ridersSaid(shown, 0), /^2 riders on the route\. Ride leader, [\d.]+ mi \([\d.]+ km\) ahead, seen just now\. Nearest rider ahead/);
  assert.match(ridersSaid(shown, null), /^2 riders on the route\. Ride leader, [\d.]+ mi \([\d.]+ km\) along the route, seen just now\.$/);
});

test("the leader's path: a reading 15 m or more from the last is added, and the path is capped", () => {
  let trail = extendTrail([], [-77, 38.9]);
  trail = extendTrail(trail, [-77.00005, 38.9]); // about 4 m: the same spot
  assert.equal(trail.length, 1);
  trail = extendTrail(trail, [-77.001, 38.9]);
  assert.equal(trail.length, 2);
  let long: readonly LonLat[] = [];
  for (let i = 0; i < TRAIL_MAX_POINTS + 10; i += 1) long = extendTrail(long, [-77 + i * 0.001, 38.9]);
  assert.equal(long.length, TRAIL_MAX_POINTS);
  assert.deepEqual(long[long.length - 1], [-77 + (TRAIL_MAX_POINTS + 9) * 0.001, 38.9]);
});

test("a follower reads with the link's leader key in a header; others send none", async () => {
  const seen: Record<string, string>[] = [];
  const get = (async (_url: string, init?: RequestInit) => {
    seen.push({ ...(init?.headers as Record<string, string>) });
    return new Response(JSON.stringify({ dots: [], alerts: [] }), { status: 200 });
  }) as typeof fetch;
  await readRide("https://x.test", "a".repeat(64), "1".repeat(32), get, KEY);
  await readRide("https://x.test", "a".repeat(64), "1".repeat(32), get);
  assert.equal(seen[0]["X-Ride-Leader"], KEY);
  assert.equal("X-Ride-Leader" in seen[1], false);
});

test("Broadcast is one small button beside Start, in Plan and Go: the share sheet, then the ride", () => {
  assert.equal(BROADCAST_LABEL, "Broadcast");
  const panel = read("../app/RoutePanel.tsx");
  const start = panel.slice(panel.indexOf("const start = rideable ? ("), panel.indexOf("const startHint"));
  // Start, then Broadcast in the same element: Go's start row and Plan's actions row both place `start`.
  assert.match(start, /className="start-button"[\s\S]*\{ride\.onBroadcast && \(\s*<button type="button" className="secondary broadcast-button" onClick=\{ride\.onBroadcast\}/);
  assert.equal((panel.match(/broadcast-button/g) ?? []).length, 1, "one control for the feature");
  assert.match(panel, /<RouteActions \{\.\.\.actions\} start=\{start\} \/>/);
  assert.match(panel, /<div className="actions start-ride go-start">\s*\{start\}/);
  const app = read("../App.tsx");
  // Only where the browser has a share sheet, as Share ride.
  assert.match(app, /broadcastRide: canShare \? broadcastRide : null/);
  // The voice unlocked within the press; the ride starts only once the link was sent and its line kept.
  const fn = app.slice(app.indexOf("const broadcastRide = () => {"), app.indexOf("\n  };\n", app.indexOf("const broadcastRide = () => {")));
  assert.match(fn, /if \(ridePrefs\.chosen \|\| mode === "go"\) primeRideVoice\(ridePrefs\);\s*void shareRoute\(true\)\.then\(\(led\) => \{\s*if \(led\) startRideChecked\(\);/);
  // The sharer's key is made before the press, so no await comes before the share sheet.
  assert.match(app, /const lead = ride && kept \? leadPrep\.current : null;/);
  assert.match(app, /useEffect\(prepareLead, \[prepareLead\]\);/);
});

test("opening a broadcast follows the leader: in Plan too, the map eased to the leader until the map is moved", () => {
  const app = read("../App.tsx");
  assert.match(app, /const SHARED_LEAD = SHARED_RIDE \? leadKeyFrom\(window\.location\.hash, window\.location\.search\) : null;/);
  assert.match(app, /const rideBroadcast = onShared\?\.ride && onShared\.id && onShared\.lead \? \{ id: onShared\.id, lead: onShared\.lead, leading: onShared\.own === true \} : null;/);
  const group = read("../RideGroup.tsx");
  assert.match(group, /void \(broadcast \? broadcastRideId\(broadcast\.id\) : rideId\(type, points\)\)/);
  assert.match(group, /if \(leading && kept\?\.answer !== "yes"\) kept = keepConsent\(id, "yes", Date\.now\(\), undefined, undefined, "lead"\);/);
  // The leader is posted on or off the route; the follower reads with the key before answering.
  assert.match(group, /const near = isBroadcast \|\| nearRoute\(line, fix\);/);
  assert.match(group, /anywhere: isBroadcast \}\)/);
  assert.match(group, /\{broadcast \? BROADCAST_CONSENT_NOTE : CONSENT_NOTE\}/);
  assert.match(group, /const token = consent\?\.token \?\? \(broadcast \? watchToken : null\);/);
  assert.match(group, /if \(following && !riding && map\) map\.easeTo\(\{ center: leaderAt, duration: 800 \}\);/);
  assert.match(group, /if \(!event\.originalEvent \|\| !followingRef\.current\) return;\s*setFollowing\(false\);/);
  // Follow the leader is a switch in the riders panel: Go's bar keeps its two buttons.
  const bar = group.slice(group.indexOf('className="ride-group-bar"'), group.indexOf("id={ridersPanel}"));
  assert.equal((bar.match(/<button/g) ?? []).length, 2);
  assert.match(group, /<span className="switch-label">\{FOLLOW_LEADER\}<\/span>/);
});
