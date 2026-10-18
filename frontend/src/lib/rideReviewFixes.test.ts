// Ride mode fixes from the 2026-10-16 review (a11y-3 and the RIDE- findings), as the page wires them.
// The engines are tested in their own files; this holds the wiring, read as source.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { REPLAN_FAILED, REPLAN_FINDING, REPLAN_FOUND, REPLAN_NO_SIGNAL, REPLAN_STILL_WAITING, replanTold } from "./navigate.ts";

const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const ride = source("../RideMode.tsx");

test("a11y-3: going off route, back on, or out of DC hands a dropped focus to Where am I? and closes the 311 menu", () => {
  const rescue = ride.slice(ride.indexOf("const shownBefore = useRef"), ride.indexOf("}, [ride.off, show311]);"));
  assert.ok(rescue.length > 100, "one rescue for both changes");
  // The decision is rideFocus.ts's (tested there); here, that the page asks it and focuses without a scroll.
  assert.match(rescue, /if \(before\.off === now\.off && before\.show311 === now\.show311\) return;/);
  assert.match(rescue, /if \(!show311\) setMenu311\(false\);/);
  assert.match(rescue, /if \(rescueRideFocus\(\{ focusWasIn: focusWasIn\.current, before, now, focusLost \}\)\) \{\s*focusWasIn\.current = null;\s*whereRef\.current\?\.focus\(\{ preventScroll: true \}\);/);
  assert.match(ride, /focusWasIn\.current = blockOf\(event\.target, \{ "311": block311\.current, off: blockOff\.current \}\);/);
  assert.match(ride, /<div className="ride-311" ref=\{block311\}/);
  assert.match(ride, /<div className="actions ride-off-actions" ref=\{blockOff\}>/);
  // After show311 is worked out, so it sees this render's value.
  assert.ok(ride.indexOf("const show311 = ride311Shown(") < ride.indexOf("const shownBefore = useRef"));
});

test("RIDE-1: hidden in the installed app, the ride's map so far goes to the last ride, and the ride keeps going", () => {
  assert.match(ride, /if \(document\.visibilityState === "hidden" && !ended\.current\) void copyCorridor\(lastRideAdopter\(\)\);/);
  const hook = ride.slice(ride.indexOf("const onHide = () =>") - 200, ride.indexOf("const onHide = () =>"));
  assert.match(hook, /if \(!handsOn\.current\) return;/, "the installed app only, as End ride's hand-on");
});

test("RIDE-3: weak GPS is shown in the ride's GPS note and said once; a good fix clears it; no new control", () => {
  const onFix = ride.slice(ride.indexOf("const onFix = useCallback("), ride.indexOf("const onFixRef = useRef(onFix);"));
  assert.match(onFix, /const weighed = weighFix\(gpsWeak\.current, fix\.accuracyM, lastFixAt\.current\);/);
  assert.match(onFix, /if \(weighed\.sayNow\) notify\(GPS_WEAK_SAID\);/);
  assert.match(onFix, /setGps\(weighed\.weak \? GPS_WEAK_SAID : ""\);/);
  // The existing note line, the one the GPS-lost notes use.
  assert.equal(ride.match(/\{gps && ride\.fix && <p className="hint">\{gps\}<\/p>\}/g)?.length, 1);
  // A new watch (Start, Resume) gives the first fixes their 12 s again.
  assert.match(ride, /stopWatch\.current\?\.\(\);\s*gpsWeak\.current = \{ goodAt: Date\.now\(\), weak: false \};/);
});

test("RIDE-3 (owner, 2026-10-16): weak GPS for long shows the turns ahead as a list, said once; a good fix brings the card back", () => {
  const onFix = ride.slice(ride.indexOf("const onFix = useCallback("), ride.indexOf("const onFixRef = useRef(onFix);"));
  assert.match(onFix, /checkCueSheet\(lastFixAt\.current\);/);
  const check = ride.slice(ride.indexOf("const checkCueSheet = useCallback("), ride.indexOf("const onFix = useCallback("));
  assert.match(check, /const sheet = cueSheetShown\(gpsWeak\.current, now, cueSheetAfterMs\(modelRef\.current, state\.progressM \?\? 0, state\.speedMs\)\);/);
  assert.match(check, /if \(sheet && !cueSheetRef\.current\) notify\(CUE_SHEET_SAID\);/);
  assert.match(check, /setCueSheetOn\(sheet\);/);
  // Also on a timer, so fixes that stop altogether bring the list too.
  assert.match(check, /window\.setInterval\(\(\) => checkCueSheet\(Date\.now\(\)\), CUE_SHEET_CHECK_MS\);/);
  // The card's distance is greyed while GPS is weak or lost (any GPS note), before the list comes.
  assert.match(ride, /<p className=\{gps \? "cue-distance cue-distance-weak" : "cue-distance"\}>/);
  assert.match(source("../styles.css"), /\.cue-distance-weak \{\s*color: var\(--text-muted\);/);
  // In the card, in place of the next cue; an ordered list with the next turn marked; no button.
  const card = ride.slice(ride.indexOf(") : cueSheetOn ? ("), ride.indexOf(") : cue && progress !== null ? ("));
  assert.match(card, /<ol className="cue-sheet-list" aria-labelledby=\{cueSheetId\}>/);
  assert.match(card, /\{cueSheet\(model, progress \?\? 0\)\.map\(/);
  assert.match(card, /aria-current=\{i === 0 \? "step" : undefined\}/);
  assert.doesNotMatch(card, /<button/);
  // Off route and arrival still come first.
  assert.ok(ride.indexOf(") : ride.off ? (") < ride.indexOf(") : cueSheetOn ? ("));
});

test("RIDE-8: a wake lock the browser lets go mid-ride is asked again, and the screen note says if it is not back", () => {
  assert.match(ride, /const note = wake\.noteFor\(held\);/, "the wording knows a lock let go from one never held");
  assert.match(ride, /useEffect\(\(\) => \{\s*wake\.whenLost\(noteWake\);\s*return \(\) => wake\.whenLost\(null\);\s*\}, \[wake, noteWake\]\);/);
  const output = source("./rideOutput.ts");
  assert.match(output, /visible: \(\) => typeof document === "undefined" \|\| document\.visibilityState === "visible"/);
});

test("RIDE-9: voice chosen after Start is unlocked inside that change's press, saying Voice on. (during a ride only)", () => {
  assert.match(ride, /export const VOICE_ON = "Voice on\.";/);
  assert.match(ride, /if \(!toVoice\(before\.output\) && toVoice\(next\.output\)\) voice\.unlock\(VOICE_ON\);/);
  const app = source("../App.tsx");
  const change = app.slice(app.indexOf("const changeRidePrefs = useCallback("), app.indexOf("const changeRidePrefs = useCallback(") + 400);
  assert.match(change, /if \(ridingNow\.current\) voiceTurnedOn\(ridePrefsNow\.current, next\);\s*writeRidePrefs\(next\);/, "only during a ride");
  assert.match(app, /const ridingNow = useRef\(riding\);\s*ridingNow\.current = riding;/);
});

test("RIDE-10: a ride note reaches the polite region itself only with neither output, as the answers do", () => {
  const notify = ride.slice(ride.indexOf("const notify = useCallback("), ride.indexOf("const noteWake = useCallback("));
  assert.match(notify, /if \(prefsRef\.current\.output === "neither"\) setPolite/);
  assert.doesNotMatch(notify, /!toScreenReader/);
});

test("RIDE-5: Re-plan from here answers every press: finding, still waiting, or no fix yet", () => {
  assert.equal(REPLAN_FINDING, "Finding a new way from here.");
  assert.equal(REPLAN_STILL_WAITING, "Still waiting for the last re-plan.");
  const press = ride.slice(ride.indexOf("const replanNow = () => {"), ride.indexOf("void replan(here, undefined, true);\n  };"));
  assert.match(press, /if \(prefsRef\.current\.output === "neither"\) setPolite/);
  assert.match(press, /if \(replanning \|\| gate\.busy\) \{\s*answer\(REPLAN_STILL_WAITING\);\s*return;/);
  assert.match(press, /if \(!here\) \{\s*answer\(NO_FIX_YET\);\s*return;/);
  assert.match(press, /answer\(REPLAN_FINDING\);\s*$/);
  assert.doesNotMatch(press, /if \(replanning\) return;/, "no silent press");
});

test("RIDE-5: the outcome of a re-plan the rider asked for is answered at every level; an automatic one keeps the levels", () => {
  for (const note of [REPLAN_FOUND, REPLAN_FAILED, REPLAN_NO_SIGNAL]) {
    for (const level of ["full", "stoker", "quiet"] as const) assert.equal(replanTold(true, level, note), "answer", `${level}: ${note}`);
  }
  assert.equal(replanTold(false, "full", REPLAN_FAILED), "say");
  assert.equal(replanTold(false, "stoker", REPLAN_FOUND), "say");
  assert.equal(replanTold(false, "stoker", REPLAN_FAILED), "quiet");
  assert.equal(replanTold(false, "quiet", REPLAN_FOUND), "quiet");
  // The page: Re-plan from here asks; the automatic re-plans do not.
  assert.match(ride, /async \(here: LonLat, via\?: LonLat, asked = false, turnRound = false\) => \{/);
  assert.match(ride, /const told = replanTold\(asked, prefsRef\.current\.verbosity, note\);/);
  // Re-plan from here, and Road closed (v0.8.2).
  assert.equal(ride.match(/void replan\([^)]*\)\)?;/g)?.filter((call) => call.includes("true")).length, 2);
});
