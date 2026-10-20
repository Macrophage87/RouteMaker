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
  assert.match(map, /if \(following\.current && map\.getBearing\(\) !== 0\) map\.easeTo\(\{ bearing: 0, padding: NO_PADDING, duration: 0 \}\)/);
  // Turning the map never moves the keyboard focus: the follow camera calls no focus().
  const follow = map.slice(map.indexOf("// Ride mode's \"you\" marker and the follow camera."), map.indexOf("// A pan or a turn of the map by hand"));
  assert.ok(follow.length > 100);
  assert.doesNotMatch(follow, /\.focus\(/);
});

test("6. an End ride button always in view, labelled End ride with its icon, one tap; Ride ended with Undo", () => {
  const top = ride.slice(ride.indexOf('className={light && cornerFits ? "ride-top"'), ride.indexOf('className={light && cornerFits ? "ride-top"') + 2400);
  assert.match(top, /<h2 id="ride-heading"/);
  // The owner, 2026-10-16 ("add a method of ending navigation"): the visible words are End ride, so its name is too.
  assert.match(top, /<button type="button" className="danger ride-end" onClick=\{end\}>\s*<Icon name="stop" size=\{18\} \/>\s*\{END_RIDE_NAME\}\s*<\/button>/);
  assert.match(ride, /export const END_RIDE_NAME = "End ride";/);
  // End ride stops the ride at once: the watch, the queued words and the voice, then App's endRide.
  const end = ride.slice(ride.indexOf("  const end = () => {"), ride.indexOf("  const keep = () => {"));
  assert.match(end, /ended\.current = true;\s*stopWatch\.current\?\.\(\);\s*stopWatch\.current = null;\s*announcer\.current\?\.drop\(\);\s*rideVoice\.stop\(\);/);
  assert.match(end, /onEnd\(/);
  assert.match(app, /onEnd=\{endRide\}/);
  const endRide = app.slice(app.indexOf("const endRide = useCallback("), app.indexOf("const undoEndRide = () => {"));
  assert.match(endRide, /setRiding\(false\);\s*setRideStart\(null\);/);
  // Review F5: the action row's duplicate End ride is gone; the sticky top End is the one End control (one, not two).
  assert.equal(ride.match(/onClick=\{end\}/g)?.length, 1);
  assert.doesNotMatch(ride, /<button type="button" className="danger" onClick=\{end\}>/);
  // Kept in view as the card scrolls, at every size and in Big text (which never hides the card).
  assert.match(css, /\.ride-top \{\s*position: sticky;\s*\/\*[^*]*\*\/\s*top: -10px;/);
  assert.doesNotMatch(css, /\.ride-big \.ride-(top|end)[^{]*\{[^}]*display: none/);
  // Ride ended, announced, with Undo for a few seconds, held while focused; Undo starts the same ride.
  // Review F6: said by the page's always-mounted polite region (not a status region mounted full), the focus on Undo.
  assert.match(ride, /<div className="ride-ended" role="group" aria-label=\{RIDE_ENDED\} \{\.\.\.hold\}>/);
  assert.doesNotMatch(ride.slice(ride.indexOf("export function RideEnded(")), /role="status"/);
  // The focus put on Undo does not hold the bar: it is released before the 8 s start (re-check of F6).
  assert.match(ride, /undo\.current\?\.focus\(\);\s*timer\.focus\(false\);\s*timer\.start\(\);/);
  assert.match(ride, /export const RIDE_ENDED_SAID = "Ride ended\. Undo available\.";/);
  assert.match(app, /announce\(from \? RIDE_ENDED_FROM_HERE_SAID : after === "no-fix" \? RIDE_ENDED_NO_FIX_SAID : RIDE_ENDED_SAID\);/);
  assert.doesNotMatch(app, /focusStartAfterRide/);
  assert.match(ride, /onFocus: \(\) => timer\.current\?\.focus\(true\)/);
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
  // Review F4: the line clears after SAID_311_MS, held while focused or hovered (the spread handlers).
  assert.match(ride, /<div className="ride-311-said" \{\.\.\.said311Timer\.hold\}>\s*\{\/\*[^*]*\*\/\}\s*<p>\{said311\}<\/p>\s*\{\/\*[^*]*\*\/\}\s*\{said311 !== REPORT_SENT && \(\s*<button type="button" className="secondary" onClick=\{addNote\}>\s*Add a note/);
  // Sent by the server already: no Add a note, which would send the same problem twice (v0.7.0 end review).
  // In the report itself the note comes after the sending.
  const fold = ride.slice(ride.indexOf("function Report311("), ride.indexOf("export function RideMode("));
  assert.ok(fold.indexOf("Add a note (optional)") > fold.indexOf("Copy the report"), "the note after the actions");
  assert.ok(fold.indexOf("Add a note (optional)") > fold.indexOf("<legend>What is it?</legend>"));
});

test("F1. Start unlocks the voice synchronously in the press, before the closure check's await", () => {
  const start = app.slice(app.indexOf("const startRideChecked = () => {"), app.indexOf("// An opened file is checked at once"));
  assert.ok(start.length > 100);
  // The handler itself is not async: nothing it does before the unlock can yield the gesture.
  assert.doesNotMatch(start, /const startRideChecked = async/);
  const prime = start.indexOf("primeRideVoice(ridePrefs)");
  assert.ok(prime > 0, "Start unlocks the voice itself");
  assert.ok(prime < start.indexOf("checkThen("), "the unlock comes before the check");
  assert.doesNotMatch(start.slice(0, prime), /await/);
  // The unlock is silent; "Ride started." is said by the ride that does start, after the check or
  // "Ride it anyway" (re-check: never said before a closure is found, always said for the ride).
  assert.match(ride, /export function primeRideVoice\(prefs: RidePrefs\): void \{\s*if \(toVoice\(prefs\.output\)\) rideVoice\.unlock\(" "\);/);
  assert.match(start, /startRide\(false\)/);
  assert.doesNotMatch(start, /startRideGesture/);
  assert.match(app, /if \(!unlocked\) startRideGesture\(prefs\);/);
  // A slow check is said politely.
  assert.match(start, /window\.setTimeout\(\(\) => announce\(CHECKING_CLOSURES\), CLOSURE_SLOW_MS\)/);
  assert.match(ride, /export const CHECKING_CLOSURES = "Checking closures…";/);
});

test("Ride settings in reach: a gear at the end of the side buttons opens them just under the top row (the owner, 2026-10-18)", () => {
  const top = ride.slice(ride.indexOf('className={light && cornerFits ? "ride-top"'), ride.indexOf("{ride.arrived ? (\n          <>"));
  // The top row: End ride, then Road closed ahead (the owner, 2026-10-19: "switch end ride and road closed"); Settings is no longer there.
  assert.doesNotMatch(top, /RIDE_SETTINGS_TEXT/);
  assert.ok(top.indexOf("END_RIDE_NAME") > 0 && top.indexOf("END_RIDE_NAME") < top.indexOf("ROAD_CLOSED_NAME"));
  assert.match(top, /\{!walking && !ride\.arrived && \(\s*<button type="button" className="secondary ride-road-closed" onClick=\{roadClosed\} aria-label=\{ROAD_CLOSED_NAME\} title=\{ROAD_CLOSED_NAME\}>/);
  // Road closed keeps its words at every size (the owner, 2026-10-20: "make everything have the big button").
  assert.match(top, /<span className="ride-top-label">\{ROAD_CLOSED_TEXT\}<\/span>/);
  assert.doesNotMatch(css, /@container|\.ride-top-label \{\s*position: absolute;/);
  assert.match(top, /ref=\{settingsPanel\}\s+id=\{`\$\{settingsId\}-settings`\}\s+className="ride-mode-settings"\s+role="group"\s+aria-label=\{RIDE_SETTINGS_TITLE\}\s+hidden=\{!settingsOpen\}\s+tabIndex=\{-1\}/);
  // The gear comes after the panel: opened, the focus goes into it; Escape there closes it, back to the gear.
  assert.match(ride, /settingsPanel\.current\?\.focus\(\{ preventScroll: true \}\);/);
  assert.match(top, /if \(event\.key === "Escape"\) \{\s*event\.preventDefault\(\);\s*setSettingsOpen\(false\);\s*settingsButton\.current\?\.focus\(\);/);
  assert.match(top, /<RideSettingsFields prefs=\{prefs\} onChange=\{onPrefs\}/);
  // The gear: the last side button, a disclosure of that panel, named Settings.
  const rail = ride.slice(ride.indexOf('<div className="ride-rail"'), ride.indexOf("{/* The bottom panel"));
  assert.match(rail, /ref=\{settingsButton\}\s+className="ride-round ride-settings-button"\s+aria-label=\{RIDE_SETTINGS_TEXT\}\s+title=\{RIDE_SETTINGS_TEXT\}\s+aria-expanded=\{settingsOpen\}\s+aria-controls=\{`\$\{settingsId\}-settings`\}/);
  assert.match(rail, /<Icon name="gear" size=\{24\} \/>\s*<\/button>\s*<\/div>\s*<\/div>\s*$/);
  assert.doesNotMatch(rail, /ride-round ride-road-closed/);
  // Opened, it is scrolled into view.
  assert.match(ride, /if \(!settingsOpen\) return;\s*settingsPanel\.current\?\.scrollIntoView\?\.\(\{ block: "nearest" \}\);/);
  // One copy of the settings: the fold at the bottom is gone.
  assert.equal(ride.match(/<RideSettingsFields prefs=\{prefs\}/g)?.length, 1);
  assert.doesNotMatch(ride, /<summary>Ride settings<\/summary>/);
  // One line (the owner, 2026-10-20): where the corner does not fit beside the buttons, measured, it is hidden from
  // view (kept for screen readers) and the light times show just under the row.
  assert.match(css, /\.ride-top \{[^}]*flex-wrap: nowrap;/);
  assert.match(css, /\.ride-top\.ride-corner-tight \.ride-heading \{\s*position: absolute;/);
  assert.match(ride, /setCornerFits\(need <= room\);/);
  // "Ride mode" itself is never shown, only said (the owner, 2026-10-20: "People know it's ride mode anyway").
  assert.match(ride, /className=\{light && cornerFits \? "ride-top" : "ride-top ride-corner-tight"\}/);
  // Then the two buttons share the whole row (the owner, 2026-10-20).
  assert.match(css, /\.ride-top\.ride-corner-tight \.ride-top-actions > \* \{\s*flex: 1 1 auto;\s*white-space: nowrap;/);
  assert.match(ride, /\{light && !cornerFits && \(\s*<p className="ride-light-below" aria-hidden="true">/);
});

test("Go's Ride sheet offers Start ride for the route its changes planned (the owner: start from the edit default)", () => {
  const sheet = app.slice(app.indexOf("<RideSheet nav={sheetNav}>"), app.indexOf("</RideSheet>"));
  assert.match(sheet, /\{goMode && shown && !stale && !riding && rideableRoute\(shown\) && \(/);
  // The same Start as the route panel's (its closure check first), the sheet closed.
  assert.match(sheet, /showPlanner\(false\);\s*startRideChecked\(\);/);
  assert.equal(sheet.match(/Start ride/g)?.length, 1);
});

test("End ride keeps the plan and its routes; part way it starts where the rider is, and Undo takes that back", () => {
  const endRide = app.slice(app.indexOf("const endRide = useCallback("), app.indexOf("const undoEndRide = () => {"));
  // Nothing about the plan is cleared: the points, the answer and its routes stay for the planner shown again.
  assert.doesNotMatch(endRide, /setPoints\(|setAnswer\(|forgetDrawn\(|setChoice\(/);
  // Part way: one edit of the points (re-planned as any edit is), a loop turned off as its finish is now a point.
  assert.match(endRide, /commit\(from, ride\.dials\.loop \? \{ \.\.\.ride, dials: \{ \.\.\.ride\.dials, loop: false \} \} : undefined\);/);
  assert.match(endRide, /announce\(from \? RIDE_ENDED_FROM_HERE_SAID : after === "no-fix" \? RIDE_ENDED_NO_FIX_SAID : RIDE_ENDED_SAID\);/);
  // The ride's own fix (planAfterEnd), never a trip's riding leg.
  assert.match(ride, /onEnd\(trip && !trip\.asPlanned \? null : planAfterEnd\(modelRef\.current, rideRef\.current, plan\.current\.points, plan\.current\.loop, Date\.now\(\)\)\);/);
  assert.match(app, /if \(ended\.from && pointsRef\.current === ended\.from\) edits\.retract\(\);/);
});

test("End ride is slid until the rider has arrived (the owner, 2026-10-19: \"Add a swipe confirmation on ending the ride unless at the destination\")", () => {
  const top = ride.slice(ride.indexOf('className={light && cornerFits ? "ride-top"'), ride.indexOf("{ride.arrived ? (\n          <>"));
  assert.match(top, /\{ride\.arrived \? \(\s*<button type="button" className="danger ride-end" onClick=\{end\}>[\s\S]*?\) : \(\s*<SlideToEnd onEnd=\{end\} onTap=\{slideHint\} \/>/);
  const slide = ride.slice(ride.indexOf("function SlideToEnd("), ride.indexOf("/** A live region"));
  // A native range, named End ride, so arrows and a screen reader's adjust gestures move it; the end ends the ride.
  assert.match(slide, /type="range"[\s\S]*min=\{0\}\s*max=\{100\}\s*step=\{25\}/);
  assert.match(slide, /aria-label=\{END_RIDE_NAME\}/);
  assert.match(slide, /if \(next >= 100\) onEnd\(\);/);
  // A tap that jumps it past half way springs back and says how; let go short of the end, it springs back.
  assert.match(slide, /if \(!byKey && next - last\.current > 50\) \{\s*back\(\);\s*onTap\(\);\s*return;/);
  // Only the range's own keys count as a step (review: a stray key let the next tap through); a pointer clears it.
  assert.match(slide, /key\.current = SLIDE_KEYS\.has\(event\.key\);/);
  assert.match(slide, /onPointerDown=\{\(\) => \{\s*key\.current = false;/);
  // Left part way by a screen reader's adjust gestures (no blur), it goes back.
  assert.match(slide, /window\.setTimeout\(back, SLIDE_BACK_MS\)/);
  assert.match(slide, /onPointerUp=\{\(\) => \{\s*if \(last\.current < 100\) back\(\);/);
  assert.match(ride, /const slideHint = \(\) => \{\s*showToast\(SLIDE_TO_END_HINT\);\s*announcer\.current\?\.answer\(SLIDE_TO_END_HINT\);/);
  // The light times take the corner inside the heading, which stays Ride mode for screen readers; the times said in words after it.
  assert.match(top, /className=\{light \? "ride-heading ride-light" : "ride-heading"\}>\s*\{light \? \(\s*<>\s*<span className="visually-hidden">Ride mode<\/span>\s*<span className="ride-light-lines" aria-hidden="true">/);
  assert.match(top, /\{light && <p className="visually-hidden">\{light\.said\}<\/p>\}/);
});
