// The battery pauses and the app's heartbeat (the owner, 2026-11-01: battery audit).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RideFix } from "./navigate.ts";
import type { LonLat } from "./geo.ts";
import {
  HEARTBEAT_MS,
  PAUSE_CHECK_MS,
  PAUSE_MOVED_M,
  PausedFixes,
  STAY_M,
  STAY_MS,
  heartbeatFix,
  movedFromPause,
  stayStep,
  stayedLong,
} from "./ridePause.ts";

const HERE: LonLat = [-77.03, 38.9];
/** `m` metres north of HERE. */
const north = (m: number): LonLat => [HERE[0], HERE[1] + m / 111_320];
const fix = (point: LonLat, at: number, accuracyM = 8, speedMs: number | null = 0): RideFix => ({ point, accuracyM, speedMs, headingDeg: null, at });

test("staying within about 30 m for 10 minutes is a stay long enough to pause", () => {
  assert.equal(STAY_M, 30);
  assert.equal(STAY_MS, 10 * 60_000);
  let stay = stayStep(null, fix(HERE, 0));
  stay = stayStep(stay, fix(north(20), 5 * 60_000));
  assert.equal(stayedLong(stay, 9 * 60_000), false);
  assert.equal(stayedLong(stay, 10 * 60_000), true);
});

test("moving more than 30 m starts the stay afresh, and a poor fix changes nothing", () => {
  let stay = stayStep(null, fix(HERE, 0));
  stay = stayStep(stay, fix(north(500), 1_000, 400));
  assert.deepEqual(stay, { point: HERE, since: 0 }, "a Wi-Fi guess 500 m off is not a move");
  stay = stayStep(stay, fix(north(40), 2_000));
  assert.deepEqual(stay, { point: north(40), since: 2_000 });
  assert.equal(stayedLong(stay, 10 * 60_000), false);
  assert.equal(stayedLong(null, Number.MAX_SAFE_INTEGER), false);
});

test("paused: a reading every 30 s, and one good reading more than 30 m away resumes", () => {
  assert.equal(PAUSE_CHECK_MS, 30_000);
  assert.equal(PAUSE_MOVED_M, 30);
  assert.equal(movedFromPause(HERE, fix(north(25), 0)), false, "still at the spot");
  assert.equal(movedFromPause(HERE, fix(north(45), 0)), true, "riding off");
  assert.equal(movedFromPause(HERE, fix(north(45), 0, 60)), false, "a rough reading is not trusted (accuracy over 50 m)");
  assert.equal(movedFromPause(HERE, fix(north(45), 0, 50)), true, "50 m is good enough");
  assert.equal(movedFromPause(null, fix(north(45), 0)), false, "no spot, nothing to compare");
});

test("heartbeat: a stopped rider's last fix again, with the time now, once no fix has come for 5 s", () => {
  const last = fix(HERE, 1_000, 6, 0.4);
  assert.equal(heartbeatFix(last, 1_000, 1_000 + HEARTBEAT_MS - 1), null, "not yet");
  const beat = heartbeatFix(last, 1_000, 1_000 + HEARTBEAT_MS);
  assert.deepEqual(beat, { point: HERE, accuracyM: 6, speedMs: 0, headingDeg: null, at: 1_000 + HEARTBEAT_MS });
  assert.equal(heartbeatFix(null, 0, 60_000), null);
});

const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
const roam = readFileSync(new URL("../RoamMode.tsx", import.meta.url), "utf8");

test("Ride: arrived and stayed put, the ride pauses the way a long hide does, in the browser and the app", () => {
  const tick = ride.slice(ride.indexOf("everyTick.current = (now: number) =>"), ride.indexOf("const resumeRef"));
  // Not behind ridesHidden(): the app pauses too.
  assert.match(tick, /if \(!rideRef\.current\.arrived \|\| !stayedLong\(stay\.current, now\)\) return;/);
  for (const step of [/pausedRef\.current = true;/, /setPaused\(true\);/, /void wake\.letGo\(\);/]) assert.match(tick, step);
  // The browser's watch stops; the app's runs on (below).
  assert.match(tick, /if \(!ridesHidden\(\)\) \{\s*stopWatch\.current\?\.\(\);\s*stopWatch\.current = null;\s*\}/);
  assert.match(ride, /\{pausedWhy === "arrived" \? ARRIVED_PAUSED_SAID : PAUSED_SAID\}/, "Resume offered with its own words");
  // The browser's hidden-page pause stays as it was: no readings for it.
  assert.match(ride, /if \(!paused \|\| pausedWhy !== "arrived"\) return;/);
});

test("Ride and Roam: paused for staying put, a reading every 30 s, and riding off carries on as Resume does", () => {
  for (const [name, src] of [["Ride", ride], ["Roam", roam]] as const) {
    assert.match(src, /window\.setInterval\(\(\) => \{[^]*?readOnce\(env, \(reading\) => \{[^]*?movedFromPause\(pauseSpot\.current, reading\)[^]*?\}, PAUSE_CHECK_MS\);/, name);
  }
  assert.match(ride, /resumeRef\.current\(true\)/);
  assert.match(roam, /resume\(true\)/);
});

test("Roam: 10 minutes hidden in a browser pauses it (not in the app), and so do 10 minutes not moving, anywhere", () => {
  assert.match(roam, /if \(!ridesHidden\(\)\) timer = window\.setTimeout\(\(\) => pause\("hidden"\), HIDDEN_STOP_MS\);/);
  assert.match(roam, /if \(pausedRef\.current \|\| !stayedLong\(stay\.current, now\)\) return;\s*pause\("still"\);/);
  assert.match(roam, /stillTick\.current\(Date\.now\(\)\);/);
  assert.match(roam, /data-resume="roam" onClick=\{\(\) => resume\(\)\}/);
});

test("Ride: the heartbeat runs only the stillness clocks, never the line or off route", () => {
  const beat = ride.slice(ride.indexOf("(fix: RideFix, beat = false) => {"), ride.indexOf("const auto = !keepRef.current"));
  assert.match(beat, /if \(beat\) \{\s*stepDockRef\.current\(fix\);\s*return;\s*\}/);
  assert.match(beat, /weighFix\(gpsWeak\.current/);
  assert.doesNotMatch(beat, /tripStep\(/, "the beat returns before the ride's step");
  assert.match(ride, /if \(ridesHidden\(\) && stopWatch\.current\) \{/, "the app only: a browser's GPS sends fixes standing still");
});

test("heartbeat: never after a poor fix or at speed, so lost GPS still shows as lost", () => {
  assert.equal(heartbeatFix(fix(HERE, 0, 80, 0), 0, 60_000), null, "a poor fix is not kept alive");
  assert.equal(heartbeatFix(fix(HERE, 0, 6, 6), 0, 60_000), null, "riding at 6 m/s and the fixes stop: a tunnel, not a stop");
  assert.notEqual(heartbeatFix(fix(HERE, 0, 6, null), 0, 60_000), null, "no speed given: taken as stopped");
});

test("app pause: the watch's fixes are only held, and the latest since the last check is the one reading", () => {
  const held = new PausedFixes();
  assert.equal(held.take(), null, "standing still the 4 m filter sends none: no check");
  held.hold(fix(north(10), 1_000));
  held.hold(fix(north(20), 2_000));
  held.hold(fix(north(45), 3_000));
  const reading = held.take();
  assert.deepEqual(reading, fix(north(45), 3_000), "the latest of the 30 s, not each fix");
  assert.equal(movedFromPause(HERE, reading!), true);
  assert.equal(held.take(), null, "each fix is checked once");
  held.hold(fix(north(45), 4_000));
  held.clear();
  assert.equal(held.take(), null, "a new pause or Resume starts with none");
});

test("Ride and Roam in the app: paused, the native watch runs on and its fixes skip the ride's work", () => {
  // Android 14+ refuses to start a location foreground service in the background: no new watch while paused or at an
  // automatic resume in the app (the owner, 2026-11-01: battery audit).
  for (const [name, src] of [["Ride", ride], ["Roam", roam]] as const) {
    const check = src.slice(src.indexOf("const timer = window.setInterval(() => {\n      // The app:"), src.indexOf("}, PAUSE_CHECK_MS);"));
    assert.match(check, /if \(ridesHidden\(\)\) \{\s*const held = pausedFixes\.take\(\);[^]*?movedFromPause\(pauseSpot\.current, held\)[^]*?return;\s*\}/, `${name}: the held fix, not readOnce`);
    assert.ok(check.indexOf("return;") < check.indexOf("readOnce("), `${name}: readOnce is the browser's only`);
  }
  assert.match(ride, /if \(pausedRef\.current\) pausedFixes\.hold\(fix\);\s*else onFixRef\.current\(fix\);/, "Ride: paused fixes draw nothing");
  assert.match(roam, /if \(pausedRef\.current\) \{\s*pausedFixes\.hold\(next\);\s*return;\s*\}/, "Roam: paused fixes draw nothing");
  assert.match(ride, /if \(ridesHidden\(\) && stopWatch\.current\) gpsWeak\.current = [^;]+;\s*else startWatch\(\);/, "Ride: Resume keeps the app's watch");
  assert.match(roam, /if \(!\(ridesHidden\(\) && stopWatch\.current\)\) startWatch\(\);/, "Roam: Resume keeps the app's watch");
  assert.match(roam, /if \(!\(why === "still" && ridesHidden\(\)\)\) \{\s*stopWatch\.current\?\.\(\);/, "Roam: only the app's still pause keeps it");
});
