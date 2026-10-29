// The ride screen's labelled buttons, short notices and steady cue card (the UI review, 2026-10-28): the plain parts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { cueParts } from "./cueShown.ts";
import { GAP_PX, PILL_PX, ROUND_PX, WORD_PX, railFit } from "./railFit.ts";
import { WAKE_LOST, WAKE_SHORT, WAKE_STEPS, WAKE_UNAVAILABLE, phoneKind, wakeSaid } from "./rideOutput.ts";
import { ROAD_CLOSED_NAME, ROAD_CLOSED_TEXT } from "./roadClosed.ts";
import { detourRowShown, type Nearby } from "./nearest.ts";
import { RESUME_HEADING, resumeHeading } from "./rideResume.ts";

const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const ride = source("../RideMode.tsx");
const roam = source("../RoamMode.tsx");
const css = source("../styles.css");

test("Go round: shown words that say what the press does, which start its name (WCAG 2.5.3)", () => {
  assert.equal(ROAD_CLOSED_TEXT, "Go round");
  assert.equal(ROAD_CLOSED_NAME, "Go round: road closed ahead");
  assert.ok(ROAD_CLOSED_NAME.startsWith(ROAD_CLOSED_TEXT));
});

test("the cue's big line names a street: a turn without one takes the next named turn after it", () => {
  assert.deepEqual(cueParts("Right, then immediately right onto Union Station Drive Northeast."), {
    head: "Right, then right onto Union Station Dr NE",
    rest: "",
  });
  assert.deepEqual(
    cueParts("Bear left onto the path, then immediately left onto Corregidor Street Northwest, then immediately right onto N Street Northwest."),
    { head: "Bear left onto the path, then left onto Corregidor St NW", rest: "Then right onto N St NW." },
  );
  // A named turn keeps its line; a "then" with no name stays in the small print; other small print is left as it is.
  assert.deepEqual(cueParts("Right onto 6th Street, then immediately bear left onto Rhode Island Avenue."), {
    head: "Right onto 6th St",
    rest: "Then bear left onto Rhode Island Ave.",
  });
  assert.deepEqual(cueParts("Right, then immediately left."), { head: "Right", rest: "Then left." });
  assert.deepEqual(cueParts("Busy crossing, signal."), { head: "Busy crossing", rest: "Signal." });
});

test("the cue card keeps its height: a two-line slot for the instruction, one line after it, a long street shrunk to fit", () => {
  assert.match(css, /\.ride \.cue-next \.cue-text \{\s*height: 3\.75rem;/);
  assert.match(css, /\.ride \.cue-next \.cue-text > \[aria-hidden\] \{[^}]*-webkit-line-clamp: 2;/);
  assert.match(css, /\.ride \.cue-next \.cue-more \{\s*min-height: 1\.25em;[^}]*-webkit-line-clamp: 1;/);
  // Large text fits the instruction to the card itself, unclamped.
  assert.match(css, /\.ride-large \.cue-next \.cue-text \{\s*height: auto;\s*display: block;/);
  assert.match(css, /\.ride-large \.cue-next \.cue-text > \[aria-hidden\] \{\s*display: inline;\s*overflow: visible;/);
  // Never under the ride's 20 px for street names (the owner, 2026-10-20), the small print and the weak-GPS rows too.
  assert.match(ride, /const CUE_TEXT_MIN_PX = 20;/);
  assert.match(css, /\.ride \.cue-more \{\s*font-size: 20px;\s*\}/);
  assert.match(css, /\.cue-sheet-list li \{[^}]*font-size: max\(20px, 1em\);/);
  assert.match(css, /\.cue-sheet-list li\.cue-sheet-next \{\s*font-size: max\(24px, 1\.2em\);/);
  assert.match(ride, /for \(let px = Math\.floor\(parseFloat\(getComputedStyle\(line\)\.fontSize\)\) - 1; px >= CUE_TEXT_MIN_PX; px -= 1\)/);
  // The small print is always there, empty too, so the card does not change height between cues.
  assert.match(ride, /<p className="cue-more" aria-hidden="true">\s*\{cueShown\.rest\}\s*<\/p>/);
});

test("the side buttons' words: under the round buttons where they fit, else 44 px pills, one column either way", () => {
  // Six buttons under: 6 x (56 + 18) + 5 x 6 = 474 px.
  assert.equal(railFit(474, 6), "under");
  assert.equal(railFit(473, 6), "pill");
  // The 311 and dock buttons are 4 px taller.
  assert.equal(railFit(474, 6, 1), "pill");
  assert.equal(railFit(0, 0), "under");
  assert.ok(PILL_PX >= 44 && ROUND_PX >= 44 && WORD_PX > 0 && GAP_PX > 0);
  // One column, in order, at every size: no wrap into a second column (Large text did that before).
  assert.match(css, /\.ride-rail \{[^}]*flex-direction: column;\s*flex-wrap: nowrap;/);
  assert.doesNotMatch(css, /wrap-reverse/);
  assert.match(css, /\.ride \.ride-rail-pill \.ride-round,\s*\.ride \.ride-rail-pill \.ride-311-button \{[^}]*height: 44px;/);
  // Each button's word, its name unchanged; Roam's three too, and no button added to Roam.
  for (const word of ["Locate", "Text", "Share live", "Detour", "Dock", "Skip", "Topo", "Settings"]) {
    assert.match(ride, new RegExp(`<span className="ride-word" aria-hidden="true">\\{(?:t|railWord)\\("${word}"\\)\\}</span>`), word);
  }
  assert.match(ride, /<span className="ride-word" aria-hidden="true">\{RIDE_SETTINGS_TEXT\}<\/span>/);
  assert.match(ride, /<span className="ride-word" aria-hidden="true">\{EASE_WORD\[which\]\}<\/span>/);
  assert.match(ride, /aria-label=\{follow \? t\("Where am I\?"\) : t\("Where am I\? The map stopped following you"\)\}/);
  assert.equal(roam.match(/className="ride-word"/g)?.length, 3);
  assert.equal(roam.match(/className=\{`ride-round/g)?.length ?? 0, 2);
  // More's bubbles: a column going up from More, not a row along the foot.
  assert.match(css, /\.ride-more-bubbles \{[^}]*flex-direction: column-reverse;/);
});

test("toasts across the map's top, over the side buttons, never cut behind them; their lines kept", () => {
  assert.match(css, /\.ride-toast \{\s*top: 8px;\s*right: 12px;\s*bottom: auto;\s*left: 12px;\s*z-index: 2;/);
  assert.match(css, /\.ride-toast p \{\s*margin: 0;\s*white-space: pre-line;/);
  assert.match(ride, /whereAmIShown\(modelRef\.current, rideRef\.current, milesRef\.current, arrivingAt\)\.join\("\\n"\)/);
});

test("the screen-on note: one line, the steps for the rider's own phone, the whole of it said", () => {
  assert.equal(WAKE_SHORT, "Screen may sleep: keep it on.");
  assert.equal(phoneKind({ userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)" }), "ios");
  assert.equal(phoneKind({ userAgent: "Mozilla/5.0 (Macintosh)", platform: "MacIntel", maxTouchPoints: 5 }), "ios");
  assert.equal(phoneKind({ userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 8)" }), "android");
  assert.equal(phoneKind({ userAgent: "Mozilla/5.0 (X11; Linux x86_64)" }), "other");
  assert.equal(phoneKind(undefined), "other");
  assert.doesNotMatch(WAKE_STEPS.android, /iPhone/);
  // The menu names show in bold; the voice and screen readers get them without the marks.
  assert.match(WAKE_STEPS.ios, /\*\*Auto-Lock\*\*, \*\*Never\*\*/);
  assert.equal(wakeSaid(WAKE_UNAVAILABLE, "ios"), `${WAKE_UNAVAILABLE} On an iPhone: Settings, Display & Brightness, Auto-Lock, Never.`);
  assert.equal(wakeSaid(WAKE_LOST, "android"), `${WAKE_LOST} On Android: Settings, Display, Screen timeout, the longest time.`);
  assert.equal(wakeSaid("", "ios"), "");
  // Ride mode and Roam show it the same way.
  assert.match(ride, /<ScreenSleepNote note=\{wakeNote\} kind=\{phone\} \/>/);
  assert.match(roam, /<ScreenSleepNote note=\{wakeNote\} kind=\{phone\} \/>/);
  const note = source("../ScreenSleepNote.tsx");
  assert.match(note, /<span aria-hidden="true">\{WAKE_SHORT\}<\/span>\s*<span className="visually-hidden">\{wakeSaid\(note, kind\)\}<\/span>/);
  assert.match(note, /<MenuStep text=\{WAKE_STEPS\[kind\]\} \/>/);
  assert.match(note, /aria-expanded=\{open\}\s+aria-controls=\{stepsId\}\s+aria-label=\{t\("How to keep the screen on"\)\}/);
});

test("detour rows: the place's own name, how far, ahead or behind; the kind's buttons give way once one is picked", () => {
  const item = (name: string | undefined, title: string): Nearby => ({
    place: { id: "n1", kind: "water", point: [0, 0], title, ...(name ? { name } : {}), details: ["Bottle filler."] },
    distanceM: 805,
    timeS: 300,
    byBike: true,
  });
  assert.equal(detourRowShown(item("Peirce Mill", "Drinking water, Peirce Mill"), "behind"), "Peirce Mill · 0.5 mi (0.8 km) behind");
  assert.equal(detourRowShown(item(undefined, "Drinking water"), "ahead"), "Drinking water · 0.5 mi (0.8 km) ahead");
  assert.equal(detourRowShown(item("Peirce Mill", "Drinking water, Peirce Mill"), null), "Peirce Mill · 0.5 mi (0.8 km)");
  assert.match(ride, /\{detourKind === null \? \(\s*<div className="actions nearest-kinds" ref=\{detourKinds\}>/);
  assert.match(ride, /aria-label=\{t\("Change what to find"\)\}/);
  // The help line is for screen readers only now; each row's whole line too.
  assert.match(ride, /<p className="visually-hidden">\{DETOUR_HELP\}<\/p>/);
  assert.match(ride, /<span className="visually-hidden">\{nearbyText\(item\)\}<\/span>/);
});

test("the ride's settings: one line on the risk in view, the rest under About Ride mode", () => {
  assert.match(ride, /<p className="hint">\{RIDE_SAFETY_SHORT\}<\/p>\s*<details className="ride-safety-more">\s*<summary>\{t\("About Ride mode"\)\}<\/summary>\s*<p className="hint">\{RIDE_SAFETY\}<\/p>/);
  assert.match(ride, /export const RIDE_SAFETY_SHORT = t\("You ride at your own risk; the route can be wrong\."\);/);
});

test("Resume names the ride where it can, and its buttons are full-size targets", () => {
  assert.equal(resumeHeading("Union Station"), "Resume your ride to Union Station?");
  assert.equal(resumeHeading(null), RESUME_HEADING);
  assert.match(css, /\.resume-ride-dialog \.closure-choices button \{\s*min-height: 44px;/);
});
