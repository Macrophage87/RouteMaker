// A broadcast ride (Stephen 2026-10-22: "allow both plan and go rides to be started as broadcasts where the ride
// leader is the person who shared. Opening the link will follow the leader and share the path"; "Have that as like a
// small button next to start"; "You then get a share screen and send it").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { LonLat } from "./geo.ts";
import {
  CONSENT_KEY,
  PATH_EVERY_MS,
  PATH_MAX_POINTS,
  PRIVATE_START_M,
  TRAIL_MAX_POINTS,
  broadcastRideId,
  consentFor,
  extendTrail,
  keepConsent,
  leadConsent,
  leaderKey,
  pathDue,
  readRide,
  rideId,
  ridersSaid,
  roleKey,
  routeKeyOf,
  shownDots,
  thinLine,
  withoutStart,
} from "./rideGroup.ts";
import { BROADCAST_SHARE_FAILED, asRideLink, leadKeyFrom, rideLinkFrom } from "./sharedRoutes.ts";
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
  // Everywhere (Stephen 2026-10-26, in the phone app: "I don't seem to be able to broadcast rides"): with no share
  // sheet, the link is copied (broadcastNav).
  assert.match(app, /broadcastRide: \{ onPress: broadcastRide, onHold: broadcastQr, note: broadcastNote \},/);
  // The voice unlocked within the press; the ride starts only once the link was sent and its line kept.
  const fn = app.slice(app.indexOf("const broadcastRide = () => {"), app.indexOf("\n  };\n", app.indexOf("const broadcastRide = () => {")));
  assert.match(fn, /\}\s*primeRideVoice\(ridePrefs\);[\s\S]*void shareRoute\(true, broadcastNav\)\.then\(\(\{ led, said \}\) => \{\s*if \(led\) \{[^}]*startRideNoted\(canShare \? "" : BROADCAST_COPIED\);\s*\} else if \(said\) setBroadcastNote/);
  // What went wrong is shown and said beside the button.
  assert.match(panel, /<p className="hint broadcast-note" role="status">/);
  // The same line shared again goes with the same leader key; the ride starts with the sharer free to re-route.
  assert.match(app, /const lead = again \? again\.lead : ride && kept \? \(\(sharedId \? leads\.current\.get\(sharedId\) : undefined\) \?\? leadPrep\.current\) : null;/);
  assert.match(app, /const opened = sharedOpenNow\.current\?\.answer === route \? sharedOpenNow\.current : null;/);
  // The sharer's key is made before the press, so no await comes before the share sheet.
  assert.match(app, /useEffect\(prepareLead, \[prepareLead\]\);/);
});

test("opening a broadcast follows the leader: in Plan too, the map eased to the leader until the map is moved", () => {
  const app = read("../App.tsx");
  assert.match(app, /const SHARED_LEAD = SHARED_RIDE \? leadKeyFrom\(window\.location\.hash, window\.location\.search\) : null;/);
  assert.match(app, /const rideBroadcast = onShared\?\.ride && onShared\.id && onShared\.lead \? \{ id: onShared\.id, lead: onShared\.lead, leading: onShared\.own === true \} : null;/);
  const group = read("../RideGroup.tsx");
  assert.match(group, /void \(broadcast \? \(broadcast\.roam \? roamRideId\(broadcast\.id\) : broadcastRideId\(broadcast\.id\)\) : rideId\(type, points\)\)/);
  // Shown as it shares, but a later "No" stands.
  assert.match(group, /if \(leading && kept === null\) kept = keepConsent\(id, "yes", Date\.now\(\), undefined, undefined, "lead"\);/);
  // The leader is posted on or off the route; the follower reads with the key before answering.
  // Off the route only while riding: after End ride the quarter-mile rule and its stop are back.
  assert.match(group, /const near = \(isBroadcast && \(riding \|\| line\.length === 0\)\) \|\| nearRoute\(line, fix\);/);
  // The leader's route and path, sent while riding when due; a follower draws the phone's own over what it saw.
  assert.match(group, /if \(!leading \|\| !riding \|\| !shareOn \|\| !front \|\| !ride \|\| !token\) return;[\s\S]*?if \(!pathDue\(pathSent\.current\.at, pathSent\.current\.routeKey, routeNowKey, t\)\) return;[\s\S]*?void sendPath\(origin, ride, token, routeNow, ownTrail\)\.then\(\(ok\) => \{\s*if \(!ok && pathSent\.current\.at === t\) pathSent\.current = \{ at: t - PATH_EVERY_MS \+ PATH_MIN_GAP_MS, routeKey: "" \};/);
  assert.match(group, /const shownTrail = sentPath && sentPath\.trail\.length >= trail\.length \? sentPath\.trail : trail;/);
  assert.match(group, /const kinds = \["dragstart", "zoomstart", "rotatestart"\] as const;/);
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

test("the leader's path goes again about every 2 minutes or when the route changes, never sooner than the server takes", () => {
  const route: LonLat[] = [
    [-77, 38.9],
    [-76.99, 38.91],
  ];
  const key = routeKeyOf(route);
  assert.equal(pathDue(0, "", key, 1_000_000), true, "the first");
  assert.equal(pathDue(1_000_000, key, key, 1_000_000 + 60_000), false, "the same route a minute later");
  assert.equal(pathDue(1_000_000, key, key, 1_000_000 + PATH_EVERY_MS), true, "the same route, due");
  assert.ok(PATH_EVERY_MS < 120_000, "before the server's 2 minutes run out");
  const rerouted = routeKeyOf([...route, [-76.98, 38.92]]);
  assert.equal(pathDue(1_000_000, key, rerouted, 1_000_000 + 25_000), true, "a re-route");
  assert.equal(pathDue(1_000_000, key, rerouted, 1_000_000 + 5_000), false, "not sooner than 20 s");
});

test("a sent line is at most the server's 1500 points, its ends kept, rounded to 5 decimals", () => {
  const long: LonLat[] = Array.from({ length: 4000 }, (_, i) => [-77 + i * 0.0000123456, 38.9] as LonLat);
  const thin = thinLine(long);
  assert.equal(thin.length, PATH_MAX_POINTS);
  assert.deepEqual(thin[0], [-77, 38.9]);
  assert.deepEqual(thin[thin.length - 1], [Math.round(long[3999][0] * 1e5) / 1e5, 38.9]);
  assert.equal(thinLine(long.slice(0, 3)).length, 3);
});

test("a follower's read keeps the leader's sent route and path; a malformed one is left out", async () => {
  const answer = (body: object) =>
    (async () => new Response(JSON.stringify(body), { status: 200 })) as unknown as typeof fetch;
  const path = { route: [[-77, 38.9], [-76.99, 38.91]], trail: [[-77, 38.9]], age_s: 30 };
  const got = await readRide("https://x.test", "a".repeat(64), "1".repeat(32), answer({ dots: [], alerts: [], leader_path: path }), KEY);
  assert.deepEqual(got?.leaderPath, path);
  const bad = await readRide("https://x.test", "a".repeat(64), "1".repeat(32), answer({ dots: [], alerts: [], leader_path: { route: "x", trail: [] } }), KEY);
  assert.equal(bad?.leaderPath, undefined);
});

test("the ridden path goes without its first 650 ft (200 m): rides often start at home", () => {
  const start: LonLat = [-77, 38.9];
  const near: LonLat = [-77.001, 38.9]; // about 87 m
  const away: LonLat = [-77.003, 38.9]; // about 260 m
  assert.deepEqual(withoutStart([start, near]), []);
  assert.deepEqual(withoutStart([start, near, away, [-77.004, 38.9]]), [away, [-77.004, 38.9]]);
  assert.equal(PRIVATE_START_M, 200);
});

test("on a computer Broadcast asks before the share sheet: Go back sends nothing, Start anyway shares then rides", () => {
  const app = read("../App.tsx");
  const fn = app.slice(app.indexOf("const broadcastRide = () => {"), app.indexOf("\n  };\n", app.indexOf("const broadcastRide = () => {")));
  // The question comes first, before the voice and the share sheet (review S1).
  assert.match(fn, /^const broadcastRide = \(\) => \{\s*if \(!computerOk\.current && askBeforeStart\(looksLikePhone\(\), tabSession\(\)\)\) \{\s*setComputerAsk\("broadcast"\);\s*return;\s*\}/);
  assert.ok(fn.indexOf('setComputerAsk("broadcast")') < fn.indexOf("shareRoute(true, broadcastNav)"));
  const dialog = app.slice(app.indexOf("<StartOnComputerDialog"), app.indexOf("<ClosureDialog"));
  assert.match(dialog, /onBack=\{\(\) => setComputerAsk\(null\)\}/);
  assert.match(dialog, /if \(asked === "broadcast"\) broadcastRide\(\);\s*else if \(asked === "qr"\) broadcastQr\(\);\s*else startRideChecked\(\);/);
});

test("Broadcast's own share-sheet failure: the ride did not start, with no Copy link it cannot use", () => {
  assert.equal(BROADCAST_SHARE_FAILED, "Could not open the share sheet, so the ride did not start.");
  const app = read("../App.tsx");
  assert.match(app, /setBroadcastNote\(\(n\) => \(\{ text: said === SHARE_FAILED \? \(canShare \? BROADCAST_SHARE_FAILED : BROADCAST_COPY_FAILED\) : said, count: n\.count \+ 1 \}\)\)/);
});

test("the ride leader is said once: not again as the nearest rider or as its role (review S4)", () => {
  const leaderOnly = shownDots(LINE, [{ lon: -77.03, lat: 38.9, age_s: 5, role: "lead", leader: true }]);
  assert.match(ridersSaid(leaderOnly, 0), /^1 rider on the route\. Ride leader, [\d.]+ mi \([\d.]+ km\) ahead, seen just now\.$/);
  const withSweep = shownDots(LINE, [
    { lon: -77.03, lat: 38.9, age_s: 5, role: "lead", leader: true },
    { lon: -77.02, lat: 38.9, age_s: 5, role: "lead" },
    { lon: -77.035, lat: 38.9, age_s: 5, role: "sweep" },
  ]);
  const said = ridersSaid(withSweep, 0);
  assert.equal((said.match(/Ride leader/g) ?? []).length, 1);
  // The nearest other rider ahead is the sweep, not the leader; the other Lead line rider is still said.
  assert.match(said, /^3 riders on the route\. Ride leader, [\d.]+ mi \([\d.]+ km\) ahead, seen just now\. Nearest rider ahead, [\d.]+ mi \([\d.]+ km\), seen just now\. Lead line, [\d.]+ mi \([\d.]+ km\) ahead\. Sweep, /);
  assert.equal(said.match(/Nearest rider ahead, ([\d.]+ mi)/)?.[1], said.match(/Sweep, ([\d.]+ mi)/)?.[1]);
  // The key: the leader under Ride leader only.
  assert.deepEqual(roleKey(leaderOnly), []);
  assert.deepEqual(roleKey(withSweep).map((k) => [k.role, k.count]), [["lead", 1], ["sweep", 1]]);
  const group = read("../RideGroup.tsx");
  assert.match(group, /\{\(leaderInKey \|\| roleRows\.length > 0\) && \(\s*<ul role="list" className="ride-role-key"/);
});

test("a ride's riders and Alert sit just under the cue card, never over the turn's arrow and distance (review B1)", () => {
  const css = read("../styles.css");
  assert.match(css, /\.app\.riding \.ride-group \{\s*top: calc\(var\(--ride-card-bottom, 64px\) \+ 8px\);\s*\}/);
  const ride = read("../RideMode.tsx");
  assert.match(ride, /app\.style\.setProperty\("--ride-card-bottom", `\$\{Math\.round\(card\.getBoundingClientRect\(\)\.bottom - app\.getBoundingClientRect\(\)\.top\)\}px`\)/);
  assert.match(ride, /watch\.observe\(card\);\s*place\(\);\s*return \(\) => \{\s*watch\.disconnect\(\);\s*app\.style\.removeProperty\("--ride-card-bottom"\);/);
});

// Opening a broadcast goes into Ride mode (Stephen 2026-10-26: "Opening the broadcast mode should enter ride mode with
// the leader's dot shown").
// Closures are the leader's (Stephen 2026-10-26: "The closure part should be leader only").
test("opensIntoRide: a phone, not over a ride or the Resume question", async () => {
  const { opensIntoRide } = await import("./rideGroup.ts");
  const at = { phone: true, onBike: false, resumeAsked: false };
  assert.equal(opensIntoRide(at), true);
  assert.equal(opensIntoRide({ ...at, phone: false }), false, "a computer watches the leader instead");
  assert.equal(opensIntoRide({ ...at, onBike: true }), false);
  assert.equal(opensIntoRide({ ...at, resumeAsked: true }), false);
});

test("App judges a followed broadcast once, when ready, and starts its ride with no closure check (the leader's), or Roam", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const sharedFollow = sharedOpen\?\.ride === true && !!sharedOpen\.lead && !sharedOpen\.own && shown === sharedOpen\.answer && !stale && rideableRoute\(shown\);/);
  assert.match(app, /if \(!ready \|\| autoRode\.current\) return;\n\s+autoRode\.current = true;\n\s+if \(!opensIntoRide\(\{ phone: looksLikePhone\(\), onBike, resumeAsked: leftAsk !== null \}\)\) return;/);
  assert.match(app, /openSaved\(shared, SHARED_OPENED\(shared\.name\), !\(SHARED_RIDE && SHARED_LEAD && shared\.answer\)\);/);
  assert.match(app, /if \(check\) void checkThen\("open", saved\.line, false, \(\) => \{\}\);/);
  assert.match(app, /if \(!shown \|\| followsBroadcast\(shown\)\) return startRide\(false\);/);
  assert.match(app, /return !!open && open\.ride && !!open\.lead && !open\.own && open\.answer === route;/);
  // Started with no press: it says so, and how to wake a phone's quiet voice (the end review's a11y finding).
  assert.match(app, /if \(sharedFollow\) startRideNoted\(BROADCAST_FOLLOWING\);\n\s+else \{\n\s+startRoam\(\);[^}]*announce\(BROADCAST_FOLLOWING\), START_NOTE_MS\);/);
  assert.match(app, /if \(plan\.verbatim && check\) void checkThen\("open", plan\.verbatim\.track, true/);
  assert.match(app, /if \(!ridingNow\.current && !roamingNow\.current\) return;\n\s+document\.removeEventListener\("click", unlock, true\);\n\s+if \(!window\.speechSynthesis\?\.speaking\) primeRideVoice\(ridePrefsNow\.current\);/);
  assert.match(app, /document\.addEventListener\("click", unlock, true\);/);
});
