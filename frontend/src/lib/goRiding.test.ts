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
const summary = source("../RideSummaryCard.tsx");
const css = source("../styles.css");

test("1. track-up by default, the ride settings' switch remembered on this device", () => {
  assert.match(app, /const \[headingUp, setHeadingUpState\] = useState\(\(\) => readHeadingUp\(\)\);/);
  assert.match(app, /writeHeadingUp\(on\);\s*setHeadingUpState\(on\);/);
  // The one control: the switch in Ride settings, unchanged.
  assert.equal(ride.match(/Turn the map to my heading/g)?.length, 1);
  assert.match(ride, /checked=\{headingUp\} onChange=\{\(event\) => onHeadingUp\(event\.target\.checked\)\}/);
  // Until a heading comes, the phone's compass (lib/compassHeading.ts) or else north-up; north-up again once the ride is over.
  assert.match(map, /props\.headingUp && compassDeg\.current !== null\s*\? compassDeg\.current\s*: props\.headingUp && following\.current\s*\? map\.getBearing\(\)\s*: 0/);
  assert.match(map, /if \(following\.current && map\.getBearing\(\) !== 0\) map\.easeTo\(\{ bearing: 0, padding: NO_PADDING, duration: 0 \}\)/);
  // Turning the map never moves the keyboard focus: the follow camera calls no focus().
  const follow = map.slice(map.indexOf("// Ride mode's \"you\" marker and the follow camera."), map.indexOf("// A pan or a turn of the map by hand"));
  assert.ok(follow.length > 100);
  assert.doesNotMatch(follow, /\.focus\(/);
});

test("6. an End ride button always in view, labelled End ride with its icon, one tap; the ride's summary with Done and Undo", () => {
  const top = ride.slice(ride.indexOf('className={light && cornerFits ? "ride-top"'), ride.indexOf('className={light && cornerFits ? "ride-top"') + 2400);
  assert.match(top, /<h2 id="ride-heading"/);
  // The owner, 2026-10-16 ("add a method of ending navigation"): the visible words are End ride, so its name is too.
  assert.match(top, /<button type="button" className="danger ride-end" onClick=\{end\}>\s*<Icon name="stop" size=\{22\} \/>\s*\{END_RIDE_NAME\}\s*<\/button>/);
  assert.match(ride, /export const END_RIDE_NAME = t\("End ride"\);/);
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
  // Kept in view as the card scrolls, at every size and in Large text.
  assert.match(css, /\.ride-top \{\s*position: sticky;\s*\/\*[^*]*\*\/\s*top: -10px;/);
  assert.doesNotMatch(css, /\.ride-big \.ride-(top|end)[^{]*\{[^}]*display: none/);
  // The ride's summary (the owner, 2026-10-20), with Done and Undo; Undo starts the same ride.
  // Review F6: said by the page's always-mounted polite region (not a status region mounted full), the focus on Done.
  // Not timed (WCAG 2.2.1): it stays until Done, Undo or Escape.
  assert.match(summary, /<section className="ride-summary" aria-labelledby=\{titleId\}>/);
  assert.doesNotMatch(summary, /key === "Escape"/);
  // Fits the screen (the owner, 2026-10-20: "scaled to fill the page, not go over"): a max height of the screen, the
  // figures scrolling only inside it, Done and Undo outside the scrolling part.
  assert.match(css, /\.ride-summary \{[^}]*max-height: calc\(100dvh - 16px - env\(safe-area-inset-top\) - env\(safe-area-inset-bottom\)\);[^}]*display: flex;/);
  // Plain vh first, for WebViews without dvh (Android 7 and up).
  assert.match(css, /\.ride-summary \{[^}]*max-height: calc\(100vh - 16px\);\s*max-height: calc\(100dvh/);
  assert.match(css, /\.ride-summary-body \{[^}]*min-height: 0;\s*overflow-y: auto;/);
  assert.match(summary, /<div\s+ref=\{body\}\s+className="ride-summary-body"\s+role=\{scrolls \? "group" : undefined\}\s+aria-labelledby=\{scrolls \? titleId : undefined\}\s+tabIndex=\{scrolls \? 0 : undefined\}\s*>[\s\S]*<\/figure>\s*\)\}\s*<\/div>\s*<div className="ride-summary-actions">/);
  // A tab stop only while it scrolls, with no second name the same as the section's.
  assert.match(summary, /setScrolls\(element\.scrollHeight > element\.clientHeight\)/);
  // Done: Go emptied for the next trip, Plan's plan kept (the owner, 2026-10-20).
  const finish = app.slice(app.indexOf("const finishRide = () => {"), app.indexOf("  // Roam (RoamMode.tsx)"));
  assert.match(finish, /endedRide\.current = null;\s*setRideEnded\(null\);\s*if \(mode === "go" && pointsRef\.current\.length > 0\) clearPlan\(\);\s*else backToRideOpener\(\);/);
  // Undo carries on from the ended ride's figures; a new Start begins from nought.
  assert.match(app, /setResumeStats\(ended\.stats\);\s*setRideStart\(ended\.start\);/);
  assert.match(app, /setResumeStats\(null\);\s*setRideStart\(\(before\) =>/);
  assert.match(ride, /useRef<RideStats>\(resumeStats \? statsPause\(resumeStats\) : statsStart\(Date\.now\(\)\)\)/);
  // Large text always (the owner, 2026-10-20: "Just use large for everything"), its small print never under 16 pt.
  assert.match(css, /\.ride-summary-figures dt,[^{]*\{\s*font-size: 16pt;/);
  assert.doesNotMatch(css + summary + app, /ride-summary-large/);
  assert.doesNotMatch(summary, /role="status"|aria-live/);
  assert.match(summary, /done\.current\?\.focus\(\);/);
  assert.doesNotMatch(summary, /useHoldTimer|setTimeout/);
  // Only "Ride ended." is said (the owner, 2026-10-20: "Just put ride ended."); the figures are on the card.
  assert.match(app, /announce\(\[RIDE_ENDED_SAID, note, owed > 0 \? `\$\{outstandingSaid\(owed\)\} \$\{REPORTS_WHERE\}` : null\]\.filter\(Boolean\)\.join\(" "\)\);/);
  assert.match(ride, /rideVoice\.speak\(RIDE_ENDED_SAID, true\);/);
  assert.doesNotMatch(app, /focusStartAfterRide/);
  assert.match(ride, /onFocus: \(\) => timer\.current\?\.focus\(true\)/);
  assert.match(app, /\{!riding && rideEnded && \(\s*<RideSummaryCard\s*key=\{rideEnded\.n\}[\s\S]*?onUndo=\{undoEndRide\}\s*onDone=\{finishRide\}/);
  assert.match(app, /startRideGesture\(ridePrefs\);\s*setResumeStats\(ended\.stats\);\s*setRideStart\(ended\.start\);/);
});

test("3. 311: one tap logs the pick (and sends it where the server has DC's key); no note in a ride (2026-10-21)", () => {
  const pick = ride.slice(ride.indexOf("const pick311 = (kind: ReportKind) => {"), ride.indexOf("// An answer the rider asked for"));
  assert.ok(pick.length > 100);
  assert.match(pick, /const entry = report311Log\(\)\.add\(kind, place\);/);
  assert.match(pick, /if \(serverOn311 && entry\.where === "dc"\)/);
  assert.match(pick, /sendReport311\(window\.location\.origin, kind, place, entryText\(entry\)\)/);
  assert.match(pick, /if \(sent\) report311Log\(\)\.setReported\(entry\.id, true\);/);
  assert.match(pick, /tell311\(loggedSaid\(entry\)\)/);
  assert.doesNotMatch(ride, /smsHref|sms:/, "no text message: DC's text line answers only Welcome (2026-10-20)");
  // The confirmation line under the button, and nothing to type: a rider is riding (Stephen, 2026-10-21).
  // Review F4: the line clears after SAID_311_MS, held while focused or hovered (the spread handlers).
  assert.match(ride, /<div className="ride-311-said" \{\.\.\.said311Timer\.hold\}>\s*\{\/\*[^*]*\*\/\}\s*<p>\{said311\}<\/p>\s*<\/div>/);
  assert.doesNotMatch(ride, /Add a note|Note311|setNote/);
});

test("F1. Start unlocks the voice synchronously in the press, before the closure check's await", () => {
  const start = app.slice(app.indexOf("const startRideNoted = (note: string) => {"), app.indexOf("// An opened file is checked at once"));
  assert.ok(start.length > 100);
  // The handler itself is not async: nothing it does before the unlock can yield the gesture.
  assert.doesNotMatch(start, /const startRideNoted = async/);
  assert.match(app, /const startRideChecked = \(\) => startRideNoted\(""\);/);
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
  assert.match(ride, /export const CHECKING_CLOSURES = t\("Checking closures…"\);/);
});

test("Ride settings in reach: More at the end of the side buttons opens them just under the top row (the owner, 2026-10-18; More 2026-10-24)", () => {
  const top = ride.slice(ride.indexOf('className={light && cornerFits ? "ride-top"'), ride.indexOf("{ride.arrived ? (\n          <>"));
  // The top row: End ride, then Road closed ahead (the owner, 2026-10-19: "switch end ride and road closed"); Settings is no longer there.
  assert.doesNotMatch(top, /RIDE_SETTINGS_TEXT/);
  assert.ok(top.indexOf("END_RIDE_NAME") > 0 && top.indexOf("END_RIDE_NAME") < top.indexOf("ROAD_CLOSED_NAME"));
  assert.match(top, /\{!walking && !ride\.arrived && \(\s*<button type="button" className="secondary ride-road-closed" onClick=\{roadClosed\} aria-label=\{ROAD_CLOSED_NAME\} title=\{ROAD_CLOSED_NAME\}>/);
  // Road closed keeps its words at every size (the owner, 2026-10-20: "make everything have the big button").
  assert.match(top, /<span className="ride-top-label">\{ROAD_CLOSED_TEXT\}<\/span>/);
  // No size query hides it (the Plan bar's own @container, styles.css, is the only one, and names no ride label).
  assert.doesNotMatch(css, /\.ride-top-label \{\s*position: absolute;/);
  assert.deepEqual([...css.matchAll(/@container[^{]*\{([^@]*)/g)].map((m) => /ride-/.test(m[1])), [false]);
  assert.match(top, /ref=\{settingsPanel\}\s+id=\{`\$\{settingsId\}-settings`\}\s+className="ride-mode-settings"\s+role="group"\s+aria-label=\{RIDE_SETTINGS_TITLE\}\s+hidden=\{!settingsOpen\}\s+tabIndex=\{-1\}/);
  // The Settings bubble comes after the panel: opened, the focus goes into it; Escape there closes it, back to the bubble.
  assert.match(ride, /settingsPanel\.current\?\.focus\(\{ preventScroll: true \}\);/);
  assert.match(top, /if \(event\.key === "Escape"\) \{\s*event\.preventDefault\(\);\s*setSettingsOpen\(false\);\s*settingsBubble\.current\?\.focus\(\);/);
  assert.match(top, /<RideSettingsFields prefs=\{prefs\} onChange=\{onPrefs\}/);
  // More: the last side button, a disclosure of its bubbles; the last bubble, Settings, a disclosure of that panel.
  const rail = ride.slice(ride.indexOf('<div className="ride-rail"'), ride.indexOf("{/* The bottom panel"));
  assert.match(rail, /ref=\{settingsButton\}\s+className="ride-round ride-settings-button"\s+aria-label=\{RIDE_MORE_NAME\}\s+title=\{RIDE_SETTINGS_TEXT\}\s+aria-expanded=\{moreOpen\}\s+aria-controls=\{`\$\{settingsId\}-more`\}/);
  assert.match(rail, /ref=\{settingsBubble\}\s+className="ride-round ride-settings-bubble"\s+aria-label=\{RIDE_SETTINGS_TITLE\}\s+title=\{RIDE_SETTINGS_TITLE\}\s+aria-expanded=\{settingsOpen\}\s+aria-controls=\{`\$\{settingsId\}-settings`\}/);
  assert.match(rail, /<Icon name="gear" size=\{24\} \/>\s*<\/button>(\s*<\/div>){4}\s*$/);
  assert.match(ride, /export const RIDE_SETTINGS_TEXT = "More";/);
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

test("End ride in Plan keeps the plan and its routes; part way it starts where the rider is, and Undo takes that back", () => {
  const endRide = app.slice(app.indexOf("const endRide = useCallback("), app.indexOf("const undoEndRide = () => {"));
  // Nothing about the plan is cleared: the points, the answer and its routes stay for the planner shown again.
  assert.doesNotMatch(endRide, /setPoints\(|setAnswer\(|forgetDrawn\(|setChoice\(/);
  // Part way: one edit of the points (re-planned as any edit is), a loop turned off as its finish is now a point.
  // In Go nothing is set up again (the owner, 2026-10-20): only Plan's ride moves the plan's start.
  assert.match(endRide, /if \(endedIn !== "go" && after && after !== "no-fix" && after\.points\.length >= 2\) \{/);
  assert.match(endRide, /commit\(from, ride\.dials\.loop \? \{ \.\.\.ride, dials: \{ \.\.\.ride\.dials, loop: false \} \} : undefined\);/);
  // The ride's own fix (planAfterEnd), never a trip's riding leg; the ride's figures with it.
  assert.match(ride, /onEnd\(trip && !trip\.asPlanned \? null : planAfterEnd\(modelRef\.current, rideRef\.current, plan\.current\.points, plan\.current\.loop, Date\.now\(\)\), statsRef\.current\);/);
  assert.match(app, /if \(ended\.from && pointsRef\.current === ended\.from\) edits\.retract\(\);/);
});

test("End ride is slid until the rider has arrived (the owner, 2026-10-19: \"Add a swipe confirmation on ending the ride unless at the destination\")", () => {
  const top = ride.slice(ride.indexOf('className={light && cornerFits ? "ride-top"'), ride.indexOf("{ride.arrived ? (\n          <>"));
  assert.match(top, /\{ride\.arrived \? \(\s*<button type="button" className="danger ride-end" onClick=\{end\}>[\s\S]*?\) : \(\s*<SlideToEnd onEnd=\{end\} onTap=\{slideHint\} \/>/);
  const slide = ride.slice(ride.indexOf("function SlideToEnd("), ride.indexOf("/** A live region"));
  // A native range, named End ride, so arrows and a screen reader's adjust gestures move it; the end ends the ride.
  assert.match(slide, /type="range"[\s\S]*min=\{0\}\s*max=\{100\}\s*step=\{25\}/);
  // Named End ride unless told otherwise (Roam's is End roam: RoamMode.tsx).
  assert.match(slide, /function SlideToEnd\(\{ onEnd, onTap, name = END_RIDE_NAME \}/);
  assert.match(slide, /aria-label=\{name\}/);
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
  assert.match(top, /className=\{light \? "ride-heading ride-light" : "ride-heading"\}>\s*\{light \? \(\s*<>\s*<span className="visually-hidden">\{t\("Ride mode"\)\}<\/span>\s*<span className="ride-light-lines" aria-hidden="true">/);
  assert.match(top, /\{light && <p className="visually-hidden">\{light\.said\}<\/p>\}/);
});

test("ride card: fewer words on screen, the whole of them for screen readers (the owner, 2026-10-20)", () => {
  const ride = source("../RideMode.tsx");
  assert.match(ride, /<span className="visually-hidden">\{t\("In"\)\} <\/span>/, "\"In\" before the distance stays for screen readers");
  // One TimeToGo for both to-go times (the next stop and the end, lib/arrival.ts), its "about" and "arriving about" read.
  assert.equal((ride.match(/<span className="visually-hidden">about <\/span>/g) ?? []).length, 1, "\"about\" before the to-go time stays for screen readers");
  assert.equal((ride.match(/<TimeToGo seconds=/g) ?? []).length, 2, "both to-go times");
  assert.match(ride, /<span aria-hidden="true">\{cueShown\.head\.replace\(\/\\\.\$\/, ""\)\}<\/span>\s*<span className="visually-hidden">\{cue\.rideText \?\? cue\.text\}<\/span>/, "the full stop goes from the shown head only; the whole sentence is read");
});

test("Broadcast from a ride (Stephen 2026-10-24: \"Let people broadcast from a ride\"): a side button, Share ride's link, the ride going on", () => {
  const rail = ride.slice(ride.indexOf('<div className="ride-rail"'), ride.indexOf("{/* The bottom panel"));
  // A round side button as Roam's, on while this rider leads; not once arrived.
  assert.match(rail, /\{onBroadcast && !ride\.arrived && \(\s*<button\s+type="button"\s+className=\{`ride-round broadcast-hold\$\{broadcasting \? " ride-round-on" : ""\}`\}\s+onClick=\{\(\) => void broadcast\(\)\}/);
  assert.match(rail, /<Icon name="broadcast" size=\{riders === null \? 24 : 20\} \/>/);
  // The count of riders, the leader included, is part of Broadcast (Stephen 2026-10-27), said in its name too.
  assert.match(rail, /\{riders !== null && \(\s*<span className="ride-round-count" aria-hidden="true">/);
  assert.match(rail, /\$\{riders === null \? "" : `\. \$\{countText\(riders\)\}`\}/);
  // The share sheet opens inside the press: nothing awaited before onBroadcast.
  assert.match(ride, /broadcastBusy\.current = true;\s*try \{\s*const said = await onBroadcast\(\);/);
  // App: Share ride's link (shareRoute(true)), the rider its leader; no new ride started.
  const fromRide = app.slice(app.indexOf("const broadcastFromRide = async"), app.indexOf("// Broadcast held beside Start"));
  assert.match(fromRide, /await shareRoute\(true, broadcastNav\)/);
  assert.doesNotMatch(fromRide, /startRide/);
  // Only the plan's own route, never Ride the rest's or a detour from Roam; one following another's link passes theirs
  // on (Stephen 2026-10-26: "allow participants to share that same code as well").
  assert.match(app, /onBroadcast=\{rideCanBroadcast \? broadcastFromRide : null\}/);
  // RideGroup's count goes to Broadcast, its own riders chip left out while riding; More > Riders opens its panel.
  assert.match(app, /riders=\{rideCanBroadcast && rideBroadcast && rideGroupLine \? rideRiders : null\}/);
  // The panel opened from More closes by its own Close, which the idle timer presses too.
  assert.match(source("../RideGroup.tsx"), /\{ridersElsewhere && \(\s*<button type="button" className="secondary ride-riders-close" data-idle-close aria-expanded=\{ridersOpen\}/);
  assert.match(app, /onRiders=\{setRideRiders\}\s*ridersElsewhere=\{riding && rideCanBroadcast\}\s*ridersAsk=\{ridersAsk\}/);
  assert.match(fromRide, /const followed = followedLink\(\);\s*if \(followed\) return \(await passOn\(followed, broadcastNav\)\)\.said;/);
  assert.match(app, /broadcasting=\{rideBroadcast\?\.leading === true\}/);
});

test("More on the ride screen (Stephen 2026-10-26): the route's changes and Settings as bubbles beside it, none in the settings", () => {
  const panel = ride.slice(ride.indexOf('className="ride-mode-settings"'), ride.indexOf("<RideSettingsFields prefs={prefs}"));
  const rail = ride.slice(ride.indexOf('<div className="ride-rail"'), ride.indexOf("{/* The bottom panel"));
  const bubbles = rail.slice(rail.indexOf('className="ride-more-bubbles"'));
  // The settings panel holds the settings alone.
  assert.doesNotMatch(panel, /ride-change|ease\(which\)|SKIP_STOP/);
  assert.match(bubbles, /role="group" aria-label=\{RIDE_MORE_NAME\} hidden=\{!moreOpen\}/);
  // Skip this stop is a bubble, named with the stop, its number shown; Instead of stop N stays with the nearest places.
  assert.match(bubbles, /\{!fixed && !ride\.arrived && nextStop && \(\s*<button[^>]*className="ride-round ride-skip-stop"\s+onClick=\{\(\) => fromMore\(\(\) => changeStop\(nextStop, undefined, true\)\)\}\s+aria-label=\{skipStopName\(nextStop\)\}/);
  assert.match(ride, /if \(!keepFocus\) whereRef\.current\?\.focus\(\);/);
  assert.match(rail, /onClick=\{\(\) => changeStop\(nextStop, item\.place\)\}/);
  // Each press closes the bubbles and the settings (the map back in view) and the focus goes to More.
  assert.match(ride, /const fromMore = \(press: \(\) => void\) => \{\s*setMoreOpen\(false\);\s*setSettingsOpen\(false\);\s*settingsButton\.current\?\.focus\(\);\s*press\(\);/);
  // More closed closes the settings too.
  assert.match(ride, /setMoreOpen\(false\);\s*setSettingsOpen\(false\);\s*if \(held\) settingsButton\.current\?\.focus\(\);/);
  // More is a disclosure (aria-expanded), so open bubbles hold the 30 s idle recentre (lib/idleRecentre.ts); it alone
  // is closed by the idle close, so the Settings bubble is not pressed again after More shut it.
  assert.match(rail, /aria-expanded=\{moreOpen\}/);
  assert.equal(bubbles.match(/data-idle-close/g), null);
  // One side menu at a time: Detour, dock or 311 opened closes More's bubbles, and More opened closes them.
  assert.match(ride, /setMenu311\(which === "311"\);\s*if \(which\) \{\s*setMoreOpen\(false\);\s*setSettingsOpen\(false\);/);
  assert.match(ride, /if \(!moreOpen\) \{\s*openMenu\(null\);\s*setMoreOpen\(true\);/);
  // Bubbles hidden by the attribute even with their own display.
  assert.match(css, /\.ride-more-bubbles\[hidden\] \{\s*display: none;/);
});

test("Topo lines from More (Stephen 2026-10-26: \"allow topo lines to be toggled on and off during a ride\"): a bubble, icon only, Map layers' own switch", () => {
  const rail = ride.slice(ride.indexOf('<div className="ride-rail"'), ride.indexOf("{/* The bottom panel"));
  const bubbles = rail.slice(rail.indexOf('className="ride-more-bubbles"'));
  // Always a bubble (it changes the map, not the route): not behind fixed or arrived, before Settings; a toggle with its full name.
  assert.match(bubbles, /className="ride-round ride-topo"\s+onClick=\{\(\) => fromMore\(\(\) => void toggleTopo\(\)\)\}\s+aria-label=\{TOPO_LINES_LABEL\}\s+aria-pressed=\{topoOn\}[\s\S]*?<Icon name="topo"[\s\S]*?ref=\{settingsBubble\}/);
  // The same state as Map layers' switch (lib/topoLines.ts); on only once the server has the contours, the reason said otherwise.
  assert.match(ride, /const topoOn = useTopoLines\(\);/);
  const toggle = ride.slice(ride.indexOf("const toggleTopo = async"), ride.indexOf("const ease = async"));
  assert.match(toggle, /if \(topoOn\) \{\s*setTopoLines\(false\);\s*answer\(RIDE_TOPO_OFF\);/);
  assert.match(toggle, /if \(ended\.current\) return;/, "nothing said after the ride ended");
  assert.match(toggle, /answer\(found === "offline" \? RIDE_TOPO_OFFLINE : TOPO_LINES_ROW_UNAVAILABLE\)/);
  assert.ok(toggle.indexOf("setTopoLines(true)") > toggle.indexOf('found !== "yes"'), "turned on only once found");
});
