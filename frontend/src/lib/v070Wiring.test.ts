// The v0.7.0 features as the page wires them: saved routes, the closure check, Home on sign-in and the
// others on a ride link (the plan's sections "Discord sign-in on...", "Account sync for Home", "Mass ride and
// Group Ride: see the others on the route" and "GPX export as close to identical as possible").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const app = source("../App.tsx");

test("a route opened, Start ride and Download GPX are each checked against the closures in force now", () => {
  // Start ride (Plan's and Go's) goes through the check; "Ride it anyway" goes on to the ride.
  assert.match(app, /startRide: startRideChecked/);
  // Review F1: the press unlocks the voice first, so the check's callback carries that on (startRide(unlocked)).
  assert.match(app, /void checkThen\("ride", shown\.geometry\.coordinates, false, \(\) => \{\s*window\.clearTimeout\(slow\);\s*startRide\(unlocked\);/);
  // An opened GPX file (and a saved one, which opens the same way) is checked against its own track.
  assert.match(app, /openImported: openImportedChecked/);
  assert.match(app, /if \(plan\.verbatim\) void checkThen\("open", plan\.verbatim\.track, true/);
  // A saved planned route, against its saved line; a plan link, once its first route is on screen.
  assert.match(app, /void checkThen\("open", saved\.line, false/);
  assert.match(app, /const checkFirstAnswer = useRef\(PLAN_LINK\)/);
  // Download, the secondary case.
  assert.match(app, /checkThen\("download"/);
  // Reroute replaces only the closed stretches of a file.
  assert.match(app, /spliceDetours\(pending\.line, stretches, detours\)/);
});

test("the closure dialog: a modal, heading focused first, Reroute around them the default, then the anyway choice, then Cancel", () => {
  const dialog = source("../ClosureDialog.tsx");
  assert.match(dialog, /dialog\.showModal\?\.\(\);\s*headingRef\.current\?\.focus\(\);/);
  // Escape is Cancel.
  assert.match(dialog, /onCancel=\{\(event\) => \{[^}]*event\.preventDefault\(\);\s*onCancel\(\);/);
  const order = ["{REROUTE_LABEL}", "{anywayLabel(ask.why)}", "{CANCEL_LABEL}"].map((label) => dialog.indexOf(label));
  assert.ok(order.every((i) => i > 0), JSON.stringify(order));
  assert.deepEqual(order, [...order].sort((x, y) => x - y));
  assert.match(dialog, /className="primary closure-reroute"/);
});

test("a saved route reopens as saved: the scheduler answers its plan with the saved line until it changes", () => {
  assert.match(app, /if \(saved && saved\.key === keptPlanKey\(plan\.points, plan\.preset, plan\.dials\)\)/);
  assert.match(app, /return \{ ok: true, route: saved\.answer \}/);
  // Update route only by the rider's press.
  assert.match(app, /onClick=\{updateSaved\}/);
  assert.match(app, /differsTooMuch\(saved\.distance_m, today\.route\.distance_m\)/);
});

test("signed in: account settings win on sign-in, changes save once they settle, and Home is offered, not merged", () => {
  assert.match(app, /const step = onSignIn\(account, device\)/);
  assert.match(app, /SAVE_SETTLE_MS\)/);
  assert.match(app, /setHomeAsk\(homeOffer\(deviceHome\(\), account\.home\)\)/);
  assert.match(app, /if \(move\) saveMyGoNow\(\{ \.\.\.myGoRef\.current, home: offer\.device \}, false\)/);
});

test("the others on the route show on a Mass Ride or Group Ride link only, in Go or riding", () => {
  assert.match(app, /\(goMode \|\| riding\) && isRideLink\(preset, rideGroupPoints\)/);
  const group = source("../RideGroup.tsx");
  // Ride mode's one watcher, while sharing and in front only; nothing stored or logged.
  assert.match(group, /watchRide\(browserRideEnv\(\)/);
  assert.doesNotMatch(group, /localStorage\.setItem\([^)]*fix|console\./);
});
