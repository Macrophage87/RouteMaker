// "Go riding fixes" (v0.7.0 plan, Stephen 2026-10-15) as the page wires them: track-up by default, the
// always-visible End with Undo, and 311 in one tap with the note after. The words and the engine are
// tested in navigate.test.ts, rideOutput.test.ts and report311.test.ts; this holds the wiring.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const app = source("../App.tsx");
const ride = source("../RideMode.tsx");
const map = source("../MapView.tsx");
const css = source("../styles.css");

test("1. track-up by default, the ride settings' switch remembered on this device", () => {
  assert.match(app, /const \[headingUp, setHeadingUpState\] = useState\(\(\) => readHeadingUp\(\)\);/);
  assert.match(app, /writeHeadingUp\(on\);\s*setHeadingUpState\(on\);/);
  // The one control: the switch in Ride settings, unchanged.
  assert.equal(ride.match(/Turn the map to my heading/g)?.length, 1);
  assert.match(ride, /checked=\{headingUp\} onChange=\{\(event\) => onHeadingUp\(event\.target\.checked\)\}/);
  // North-up until a heading comes; north-up again once the ride is over.
  assert.match(map, /props\.headingUp && following\.current \? map\.getBearing\(\) : 0/);
  assert.match(map, /if \(following\.current && map\.getBearing\(\) !== 0\) map\.easeTo\(\{ bearing: 0, duration: 0 \}\)/);
  // Turning the map never moves the keyboard focus: the follow camera calls no focus().
  const follow = map.slice(map.indexOf("// Ride mode's \"you\" marker and the follow camera."), map.indexOf("// A pan or a turn of the map by hand"));
  assert.ok(follow.length > 100);
  assert.doesNotMatch(follow, /\.focus\(/);
});

test("6. an End button always in view, named End ride, one tap; Ride ended with Undo; End ride stays", () => {
  const top = ride.slice(ride.indexOf('<div className="ride-top">'), ride.indexOf('<div className="ride-top">') + 600);
  assert.match(top, /<h2 id="ride-heading"/);
  assert.match(top, /<button type="button" className="danger ride-end" onClick=\{end\} aria-label=\{END_RIDE_NAME\}>/);
  assert.match(ride, /export const END_RIDE_NAME = "End ride";/);
  // The action row's End ride is still there, and does the same.
  assert.match(ride, /<button type="button" className="danger" onClick=\{end\}>\s*<Icon name="stop" size=\{20\} \/>\s*\{END_RIDE_NAME\}/);
  // Kept in view as the card scrolls, at every size and in Big text (which never hides the card).
  assert.match(css, /\.ride-top \{\s*position: sticky;\s*top: 0;/);
  assert.doesNotMatch(css, /\.ride-big \.ride-(top|end)[^{]*\{[^}]*display: none/);
  // Ride ended, announced, with Undo for a few seconds, held while focused; Undo starts the same ride.
  assert.match(ride, /className="ride-ended"\s*role="status"/);
  assert.match(ride, /onFocus=\{\(\) => window\.clearTimeout\(timer\.current\)\}/);
  assert.match(ride, /export const UNDO_END_MS = 8_000;/);
  assert.match(app, /\{!riding && rideEnded > 0 && \(\s*<RideEnded\s*key=\{rideEnded\}\s*onUndo=\{undoEndRide\}/);
  assert.match(app, /startRideGesture\(ridePrefs\);\s*setRideStart\(ended\.start\);/);
});

test("3. 311: the pick is the report (sent, or the text app filled in); the note after, never before", () => {
  const pick = ride.slice(ride.indexOf("const pick311 = (kind: ReportKind) => {"), ride.indexOf("const addNote = () => {"));
  assert.match(pick, /const way = pickWay\(serverOn311, phone\);/);
  assert.match(pick, /sendReport311\(window\.location\.origin, kind, place\)/);
  assert.match(pick, /window\.location\.assign\(smsHref\(sms, agent, touch\)\)/);
  assert.match(pick, /tell311\(REPORT_SENT\)/);
  assert.match(pick, /tell311\(REPORT_READY\)/);
  // The confirmation line and Add a note under the button.
  assert.match(ride, /<div className="ride-311-said">\s*\{\/\*[^*]*\*\/\}\s*<p>\{said311\}<\/p>\s*<button type="button" className="secondary" onClick=\{addNote\}>\s*Add a note/);
  // In the report itself the note comes after the sending.
  const fold = ride.slice(ride.indexOf("function Report311("), ride.indexOf("export function RideMode("));
  assert.ok(fold.indexOf("Add a note (optional)") > fold.indexOf("Copy the report"), "the note after the actions");
  assert.ok(fold.indexOf("Add a note (optional)") > fold.indexOf("<legend>What is it?</legend>"));
});

test("F1. Start unlocks the voice synchronously in the press, before the closure check's await", () => {
  const start = app.slice(app.indexOf("const startRideChecked = () => {"), app.indexOf("// An opened file is checked at once"));
  assert.ok(start.length > 100);
  // The handler itself is not async: nothing it does before startRideGesture can yield the gesture.
  assert.doesNotMatch(start, /const startRideChecked = async/);
  const gesture = start.indexOf("startRideGesture(ridePrefs)");
  assert.ok(gesture > 0, "Start calls startRideGesture itself");
  assert.ok(gesture < start.indexOf("checkThen("), "the gesture comes before the check");
  assert.doesNotMatch(start.slice(0, gesture), /await/);
  // The ride that follows does not unlock (speak "Ride started.") a second time.
  assert.match(app, /if \(!unlocked\) startRideGesture\(prefs\);/);
  assert.match(start, /startRide\(unlocked\)/);
  // A slow check is said politely; a closure found stops the voice the press began.
  assert.match(start, /window\.setTimeout\(\(\) => announce\(CHECKING_CLOSURES\), CLOSURE_SLOW_MS\)/);
  assert.match(start, /if \(unlocked\) rideVoice\.stop\(\);/);
  assert.match(ride, /export const CHECKING_CLOSURES = "Checking closures…";/);
});
