// The v0.18.0 release review's fixes (simplicity and accessibility), as the page wires them. The trip check's own are
// in lib/tripCheck.test.ts, the Avoid stairs words in lib/avoidStairs.test.ts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const app = source("./App.tsx");
const ride = source("./RideMode.tsx");
const dials = source("./DialsPanel.tsx");
const summary = source("./TransitSummary.tsx");
const css = source("./styles.css");

test("a walk's settings leave out the riding ones: Roads, not trails and the car-free roads hint (S1)", () => {
  assert.match(dials, /\{!onFoot\(preset\) && <p className="hint">\{t\("Weekend car-free roads/);
  assert.match(dials, /\{!onFoot\(preset\) && \(\s*<div className="dial trails-off">/);
});

test("a walk starts and ends in walk words: Walk started., End walk (N5)", () => {
  assert.match(ride, /export const WALK_STARTED = t\("Walk started\."\);/);
  assert.match(ride, /export const END_WALK_NAME = t\("End walk"\);/);
  assert.match(ride, /rideVoice\.unlock\(walk \? WALK_STARTED : RIDE_STARTED\)/);
  assert.match(app, /if \(!unlocked\) startRideGesture\(prefs, walksLine\(route\)\);/);
  assert.match(ride, /<SlideToEnd onEnd=\{end\} onTap=\{slideHint\} name=\{trip\?\.onFoot \? END_WALK_NAME : END_RIDE_NAME\} \/>/);
});

test("the stop to get off at is marked in words in the trip's steps, not by bold alone (N2)", () => {
  assert.match(summary, /<strong>\{stop\.name\}<\/strong> · \{t\("get off"\)\}/);
});

test("the ride's then-lines and stop by stop's card are the ride's 20 px (S3)", () => {
  assert.match(css, /\.ride \.cue-then,\s*\.ride \.onboard \{\s*font-size: 20px;\s*\}/);
  // Large text's own, larger size still wins: it comes after.
  assert.ok(css.indexOf(".ride-large .cue-then {") > css.indexOf(".ride .onboard {"));
});
