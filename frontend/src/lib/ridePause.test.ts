// The battery pauses and the app's heartbeat (the owner, 2026-11-01: battery audit).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RideFix } from "./navigate.ts";
import type { LonLat } from "./geo.ts";
import {
  HEARTBEAT_MS,
  HEARTBEAT_STOP_MS,
  MOVE_GOOD_M,
  PAUSE_CHECK_MS,
  PAUSE_MOVED_M,
  PausedFixes,
  ROAM_RESUMED_SAID,
  STAY_M,
  STAY_MS,
  STOPPED_BEAT_MS,
  beatKeepsGps,
  heartbeatFix,
  movedFromPause,
  rideStayPausedSaid,
  roamStayPausedSaid,
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
  assert.equal(movedFromPause(HERE, fix(north(45), 0, 60)), false, "a rough reading is not trusted");
  assert.equal(movedFromPause(null, fix(north(45), 0)), false, "no spot, nothing to compare");
});

test("indoor drift neither resumes a pause nor keeps one from starting (the owner, 2026-11-01: battery audit)", () => {
  assert.equal(MOVE_GOOD_M, 20);
  // Sat indoors: a 40 m fix drifting 45 m off is not a move.
  assert.equal(movedFromPause(HERE, fix(north(45), 0, 40)), false, "over 20 m accuracy: not trusted to resume");
  assert.equal(movedFromPause(HERE, fix(north(45), 0, 21)), false);
  // A good fix must clear 30 m plus its own accuracy.
  assert.equal(movedFromPause(HERE, fix(north(45), 0, 20)), false, "45 m is within 30 + 20");
  assert.equal(movedFromPause(HERE, fix(north(51), 0, 20)), true, "51 m clears 30 + 20");
  assert.equal(movedFromPause(HERE, fix(north(36), 0, 5)), true, "a sharp fix 36 m off clears 30 + 5");
  // The stay: drift keeps it, so the pause still comes at 10 minutes.
  let stay = stayStep(null, fix(HERE, 0, 35));
  assert.deepEqual(stay, { point: HERE, since: 0 }, "a fair fix (under 50 m) starts a stay");
  stay = stayStep(stay, fix(north(60), 3 * 60_000, 40));
  stay = stayStep(stay, fix(north(45), 6 * 60_000, 20));
  assert.deepEqual(stay, { point: HERE, since: 0 }, "drift keeps the stay");
  assert.equal(stayedLong(stay, 10 * 60_000), true);
  // Riding off with a good fix starts it afresh.
  assert.deepEqual(stayStep(stay, fix(north(60), 7 * 60_000, 10)), { point: north(60), since: 7 * 60_000 });
});

test("a rough fix far off neither resumes a pause nor starts or moves a stay", () => {
  // Far enough that only the accuracy gates decide: 200 m clears 30 + 40, 500 m clears 30 + 60.
  assert.equal(movedFromPause(HERE, fix(north(200), 0, 40)), false, "a 40 m fix 200 m off does not resume");
  assert.equal(movedFromPause(HERE, fix(north(200), 0, 20)), true, "a good fix there does");
  assert.equal(stayStep(null, fix(HERE, 0, 60)), null, "a poor fix (over 50 m) starts no stay");
  const stay = { point: HERE, since: 0 };
  assert.deepEqual(stayStep(stay, fix(north(500), 1_000, 60)), stay, "nor moves one");
});

test("heartbeat: a stopped rider's last fix again, with the time now, once no fix has come for 5 s", () => {
  const last = fix(HERE, 1_000, 6, 0.4);
  assert.equal(heartbeatFix(last, 1_000, 1_000 + HEARTBEAT_MS - 1), null, "not yet");
  const beat = heartbeatFix(last, 1_000, 1_000 + HEARTBEAT_MS);
  assert.deepEqual(beat, { point: HERE, accuracyM: 6, speedMs: 0, headingDeg: null, at: 1_000 + HEARTBEAT_MS });
  assert.equal(heartbeatFix(null, 0, 60_000), null);
});

test("heartbeat: none 60 s after a slow rider's last real fix, so a lost GPS is not kept alive (the owner, 2026-11-01)", () => {
  assert.equal(HEARTBEAT_STOP_MS, 60_000);
  const last = fix(HERE, 0, 6, 1);
  assert.notEqual(heartbeatFix(last, 0, HEARTBEAT_STOP_MS), null, "still beating at 60 s");
  assert.equal(heartbeatFix(last, 0, HEARTBEAT_STOP_MS + 1), null, "no more after");
});

test("stay-put pause words: only the app promises riding off carries on; a browser asks for Resume", () => {
  assert.equal(rideStayPausedSaid(true), "Ride paused at your destination to save battery. It carries on when you ride off, or press Resume.");
  assert.equal(rideStayPausedSaid(false), "Ride paused at your destination to save battery. Press Resume to carry on.");
  assert.equal(roamStayPausedSaid(true), "Roam paused to save battery. It carries on when you ride off, or press Resume.");
  assert.equal(roamStayPausedSaid(false), "Roam paused to save battery. Press Resume to carry on.");
  assert.equal(ROAM_RESUMED_SAID, "Roam resumed.");
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
  assert.match(ride, /\{pausedWhy === "arrived" \? rideStayPausedSaid\(ridesHidden\(\)\) : PAUSED_SAID\}/, "Resume offered with its own words");
  // The browser's hidden-page pause stays as it was: no readings for it.
  assert.match(ride, /if \(!paused \|\| pausedWhy !== "arrived"\) return;/);
});

test("Ride and Roam: paused for staying put, a reading every 30 s, and riding off carries on as Resume does", () => {
  for (const [name, src] of [["Ride", ride], ["Roam", roam]] as const) {
    assert.match(src, /window\.setInterval\(\(\) => \{[^]*?readOnce\(env, \(reading\) => \{[^]*?movedFromPause\(pauseSpot\.current, reading\)[^]*?\}, PAUSE_CHECK_MS\);/, name);
  }
  assert.match(ride, /resumeRef\.current\(true\)/);
  assert.match(roam, /resume\(true\)/);
  assert.match(roam, /if \(auto\) say\(ROAM_RESUMED_SAID\);/, "Roam says it carried on, as it said it paused");
});

test("Roam: 10 minutes hidden in a browser pauses it (not in the app), and so do 10 minutes not moving, anywhere", () => {
  assert.match(roam, /if \(!ridesHidden\(\)\) timer = window\.setTimeout\(\(\) => pause\("hidden"\), HIDDEN_STOP_MS\);/);
  assert.match(roam, /if \(pausedRef\.current \|\| !stayedLong\(stay\.current, now\)\) return;\s*pause\("still"\);/);
  assert.match(roam, /stillTick\.current\(Date\.now\(\)\);/);
  assert.match(roam, /data-resume="roam" onClick=\{\(\) => resume\(\)\}/);
});

test("Ride: the heartbeat runs only the stillness clocks, never the line or off route", () => {
  const beat = ride.slice(ride.indexOf("(fix: RideFix, beat = false) => {"), ride.indexOf("const auto = !keepRef.current"));
  // Only the stay and the dock: it returns before the weak-GPS clock and the last fix's time (a slow rider's lost GPS).
  // Only the stay and the dock, plus the GPS clocks after a stopped rider's good fix (beatKeepsGps, a red light).
  assert.match(beat, /if \(beat\) \{\s*stay\.current = [^;]+stayStep\(stay\.current, fix\)[^;]*;\s*stepDockRef\.current\(fix\);/);
  assert.match(beat, /if \(beatKeepsGps\(lastRealFix\.current, [^)]*\)\) \{\s*lastFixAt\.current = Date\.now\(\);\s*gpsWeak\.current = \{ goodAt: lastFixAt\.current, weak: false \};\s*\}\s*return;\s*\}/);
  assert.ok(beat.indexOf("if (beat) {") < beat.indexOf("weighFix(gpsWeak.current"), "the beat returns before weighFix");
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

test("stopped at a long red light with no fix, the GPS is not taken as lost; riding slowly and losing GPS still is", () => {
  // The owner, 2026-11-01: "Make sure there's some backup" for the 4 m filter. A stopped rider's good fix keeps the GPS
  // clocks through a 2-minute light; a slow rider's (1.5 m/s, under trees) does not, so the weak-GPS note still comes.
  const stopped = fix(HERE, 0, 8, 0);
  assert.equal(beatKeepsGps(stopped, 0, 120_000), true, "a 2-minute light");
  assert.ok(heartbeatFix(stopped, 0, 120_000), "beats go on through it");
  assert.equal(beatKeepsGps(stopped, 0, STOPPED_BEAT_MS + 1), false, "3 minutes on: taken as lost");
  assert.equal(heartbeatFix(stopped, 0, STOPPED_BEAT_MS + 1), null);
  const slow = fix(HERE, 0, 8, 1.5);
  assert.equal(beatKeepsGps(slow, 0, 10_000), false, "riding slowly");
  assert.equal(heartbeatFix(slow, 0, 120_000), null, "and its beats stop at a minute");
  assert.equal(beatKeepsGps(fix(HERE, 0, 8, null), 0, 10_000), false, "no speed: not known to be stopped");
  assert.equal(beatKeepsGps(fix(HERE, 0, 35, 0), 0, 10_000), false, "a rough fix");
});
