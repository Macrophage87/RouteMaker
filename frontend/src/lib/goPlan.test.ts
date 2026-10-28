// UI-CLEANUP (the approved mockup of 2026-10-11): Go and Plan, My Go, the warning line, Ride mode's 311 button
// and where App and the components place them. The pure parts are tested here; App and the .tsx components are
// read as source (testSupport/appSource.mjs), as the other panels' wiring is; the browser suite drives the DOM.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { GO_START_SAID, GO_START_UNAVAILABLE, GO_START_MAX_AGE_MS, GO_PICK_MOVED_M, GO_WARM_AFTER_MS, goWarmDue, goPickStart, goHereStart, goStartStale, MODE_LABEL, goDestinationLocating, goDestinationNeedsStart, goPickAction, goTapSetsEnd, goDestinationSet, goPressLocatingSaid, goPressNeedsStartSaid, GO_PRESS_LOCATING_SAY_MS, goStartFailedReason, goDestinationNeedsStartBecause, goPressNeedsStartBecause, goTapRoutedSaid, goPlaceName, TAB_MODE_KEY, goRouteStart, goStartLine, hasPlanLink, shouldAskGoStart, laterMyGoApplies, modeSaid, openingMode, readTabMode, writeTabMode } from "./appMode.ts";
import {
  ACCOUNT_COPY_KEY,
  DEVICE_KEY,
  GO_FIXED,
  GO_RIDES,
  HOME_NOT_SET,
  NO_MY_GO,
  fetchMyGo,
  goRideChips,
  myGoBody,
  parseMyGo,
  readStartMyGo,
  saveAccountCopy,
  saveDeviceMyGo,
  saveMyGo,
} from "./myGo.ts";
import { facilityNoticeCount, warningsLabel } from "./routeNotices.ts";
import { RIDE_311_NAME, RIDE_311_TEXT, Ride311Menu, menuPlaceLine, ride311Shown } from "./ride311.ts";
import { REPORT_KINDS } from "./report311.ts";
import { avoidLine, avoidOfferShort } from "./avoidJunctions.ts";
import { ICON_PATHS } from "./iconPaths.ts";
import { startDials } from "./dials.ts";
import { appSource } from "../testSupport/appSource.mjs";

const src = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");
const app = appSource();
const appFile = src("../App.tsx");
const go = src("../app/Go.tsx");
const ride = src("../RideMode.tsx");

/** A Storage stand-in: a Map, or one that refuses every call. */
function store(initial: Record<string, string> = {}, refuse = false) {
  const map = new Map(Object.entries(initial));
  const no = () => {
    throw new Error("refused");
  };
  return {
    map,
    getItem: refuse ? no : (k: string) => map.get(k) ?? null,
    setItem: refuse ? no : (k: string, v: string) => void map.set(k, v),
    removeItem: refuse ? no : (k: string) => void map.delete(k),
  };
}

// ---- which view the app opens in (the owner's choice 1) ------------------------------------------

test("a phone opens in Go and a wide screen in Plan; a shared link opens in Plan on a wide screen only; the tab's own view wins over all; there is no Open in (the owner, 2026-10-22)", () => {
  const base = { tab: null, planLink: false };
  assert.deepEqual(openingMode({ ...base, wide: false }), { mode: "go", by: "screen" });
  assert.deepEqual(openingMode({ ...base, wide: true }), { mode: "plan", by: "screen" });
  // A phone opens in Go even with a link (the owner, 2026-10-19), as the app's own #preset=… address is one.
  assert.deepEqual(openingMode({ ...base, planLink: true, wide: false }), { mode: "go", by: "screen" });
  assert.deepEqual(openingMode({ ...base, planLink: true, wide: true }), { mode: "plan", by: "link" });
  assert.deepEqual(openingMode({ tab: "go", planLink: true, wide: true }), { mode: "go", by: "tab" }, "a reload keeps the tab's view");
  // A saved open_in is not read to open the app.
  assert.doesNotMatch(appFile, /openingMode\(\{[^}]*openIn/);
  // The account's My Go, read after the page opened, sets Go's ride only while the view is the screen's guess, never after a switch.
  assert.equal(laterMyGoApplies("screen", false), true);
  assert.equal(laterMyGoApplies("link", false), false);
  assert.equal(laterMyGoApplies("tab", false), false);
  assert.equal(laterMyGoApplies("screen", true), false);
  assert.deepEqual(MODE_LABEL, { go: "Go", plan: "Plan", review: "Review" }, "Review: offered to an admin only (lib/review.test.ts)");
  assert.match(modeSaid("go"), /^Go/);
  assert.match(modeSaid("plan"), /^Plan/);
});

test("a plan link is one with points, a ride type, a loop or a GPX: a map position alone is not", () => {
  assert.equal(hasPlanLink(""), false);
  assert.equal(hasPlanLink("#"), false);
  assert.equal(hasPlanLink("#at=-77.03,38.9"), false);
  assert.equal(hasPlanLink("#p=-77.03,38.9;-77.01,38.89&preset=default"), true);
  assert.equal(hasPlanLink("#preset=kids"), true);
  assert.equal(hasPlanLink("#loop=1"), true);
  assert.equal(hasPlanLink("#at=1,2&p=x"), true);
  assert.equal(hasPlanLink("#pp=1"), false, "the key, not a prefix of it");
});

test("the tab's view is kept in the tab's own store, and a refused store keeps nothing and breaks nothing", () => {
  const s = store();
  assert.equal(readTabMode(s), null);
  writeTabMode("go", s);
  assert.equal(s.map.get(TAB_MODE_KEY), "go");
  assert.equal(readTabMode(s), "go");
  assert.equal(readTabMode(store({ [TAB_MODE_KEY]: "nonsense" })), null);
  const refused = store({}, true);
  assert.doesNotThrow(() => writeTabMode("plan", refused));
  assert.equal(readTabMode(refused), null);
  assert.equal(readTabMode(null), null);
});

// ---- My Go (the owner's choice 2) -------------------------------------------------------------

test("My Go reads what makes sense and drops the rest: an unknown view or ride, a Home without numbers", () => {
  assert.deepEqual(parseMyGo(null), NO_MY_GO);
  assert.deepEqual(parseMyGo("x"), NO_MY_GO);
  assert.deepEqual(parseMyGo({ open_in: "go", ride: "cargo", home: { lon: -77.0, lat: 38.9, label: "Home" } }), {
    openIn: "go",
    ride: "cargo",
    home: { point: [-77.0, 38.9], label: "Home" },
  });
  assert.deepEqual(parseMyGo({ open_in: "sideways", ride: "unicycle", home: { lon: "x", lat: 1 } }), NO_MY_GO);
  assert.deepEqual(parseMyGo({ open_in: "plan", ride: "", home: { lon: Infinity, lat: 1 } }), { openIn: "plan", ride: null, home: null });
  // The body: Default is "", a Home's label is cut to the server's 120 characters.
  assert.deepEqual(myGoBody({ openIn: "", ride: "default", home: null }), { open_in: "", ride: "", home: null });
  assert.deepEqual(myGoBody({ openIn: "go", ride: "novice", home: { point: [-77, 38.9], label: "x".repeat(200) } }).home, { lon: -77, lat: 38.9, label: "x".repeat(120) });
});

test("signed out My Go stays on this device with its Home; the account's copy opens the next visit at once and goes with a sign-out", () => {
  const s = store();
  assert.deepEqual(readStartMyGo(s), { myGo: NO_MY_GO, account: false });
  saveDeviceMyGo({ openIn: "go", ride: "cargo", home: { point: [-77, 38.9], label: "Mine" } }, s);
  assert.deepEqual(JSON.parse(s.map.get(DEVICE_KEY) as string).home, { lon: -77, lat: 38.9, label: "Mine" }, "Home without signing in, on the device");
  assert.deepEqual(readStartMyGo(s), { myGo: { openIn: "go", ride: "cargo", home: { point: [-77, 38.9], label: "Mine" } }, account: false });
  saveAccountCopy({ openIn: "plan", ride: null, home: { point: [-77, 38.9], label: "Mine" } }, s);
  assert.equal(JSON.parse(s.map.get(ACCOUNT_COPY_KEY) as string).home, null);
  assert.deepEqual(readStartMyGo(s), { myGo: { openIn: "plan", ride: null, home: null }, account: true }, "the account's copy first");
  saveAccountCopy(null, s);
  assert.equal(s.map.has(ACCOUNT_COPY_KEY), false);
  // A refused or broken store: the defaults, and no error.
  assert.deepEqual(readStartMyGo(store({}, true)), { myGo: NO_MY_GO, account: false });
  assert.deepEqual(readStartMyGo(store({ [DEVICE_KEY]: "{broken" })), { myGo: NO_MY_GO, account: false });
  assert.doesNotThrow(() => saveDeviceMyGo(NO_MY_GO, store({}, true)));
});

test("My Go is read and saved at /api/me/go, same origin, with the CSRF token; a refusal or a network error is null", async () => {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const answer = (status: number, body: unknown) => (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), { status });
  }) as unknown as typeof fetch;
  assert.deepEqual(await fetchMyGo("https://x.test", answer(200, { open_in: "go", ride: "", home: null })), { openIn: "go", ride: null, home: null });
  assert.equal(calls[0].url, "https://x.test/api/me/go");
  assert.equal(calls[0].init.credentials, "same-origin");
  assert.equal(await fetchMyGo("https://x.test", answer(401, { code: "signed_out" })), null);
  assert.equal(await fetchMyGo("https://x.test", (async () => { throw new Error("offline"); }) as unknown as typeof fetch), null);
  calls.length = 0;
  const saved = await saveMyGo("https://x.test", { openIn: "plan", ride: "novice", home: null }, answer(200, { open_in: "plan", ride: "novice", home: null }), "a=1; csrftoken=tok%3D1");
  assert.deepEqual(saved, { openIn: "plan", ride: "novice", home: null });
  // A ride saved before Riding with kids became Novice and Nervous (v0.7.0) is read as the new one.
  assert.deepEqual(await fetchMyGo("https://x.test", answer(200, { open_in: "go", ride: "kids", home: null })), { openIn: "go", ride: "novice", home: null });
  assert.equal(calls[0].init.method, "POST");
  assert.equal((calls[0].init.headers as Record<string, string>)["X-CSRFToken"], "tok=1");
  assert.deepEqual(JSON.parse(calls[0].init.body as string), { open_in: "plan", ride: "novice", home: null });
  assert.equal(await saveMyGo("https://x.test", NO_MY_GO, answer(403, {}), ""), null);
});

// ---- Go's chips (the owner's choices 3 and 10) ------------------------------------------------

test("Go's ride types: the rider's own (My Go, Default until set), then Own Bike + 🚆🚌 and Bikeshare + 🚶🚆🚌", () => {
  // The owner, 2026-10-12: "Default (user sets)", then the two transit types; Cargo and Bikeshare are under More.
  assert.deepEqual([...GO_FIXED], ["bike-transit", "bikeshare-transit"]);
  assert.deepEqual([...GO_RIDES], ["default", "bike-transit", "bikeshare-transit"]);
  assert.deepEqual(goRideChips(null), ["default", "bike-transit", "bikeshare-transit"]);
  assert.deepEqual(goRideChips("cargo"), ["cargo", "bike-transit", "bikeshare-transit"]);
  assert.deepEqual(goRideChips("novice"), ["novice", "bike-transit", "bikeshare-transit"]);
  // A stored My Go ride from before (Bikeshare was a Go chip) still works: it is the rider's own.
  assert.deepEqual(goRideChips("bikeshare"), ["bikeshare", "bike-transit", "bikeshare-transit"]);
  // The rider's own is a transit type: no chip twice, and Default fills the third place.
  assert.deepEqual(goRideChips("bike-transit"), ["bike-transit", "bikeshare-transit", "default"]);
  assert.deepEqual(goRideChips("bikeshare-transit"), ["bikeshare-transit", "bike-transit", "default"]);
  // App: the chips from My Go's ride, the first described as the rider's own; More opens the Ride sheet with every type.
  assert.match(appFile, /<RideChips ids=\{goRideChips\(myGo\.ride\)\} preset=\{preset\} onPick=\{pickRide\} more=\{\(opener\) => openView\("ride", opener\)\} label=\{t\("Ride type"\)\} ownHint=\{OWN_RIDE_HINT\} \/>/);
  assert.match(src("../app/Sheets.tsx"), /aria-describedby=\{ownHint && index === 0 \? "ride-own-hint" : undefined\}/);
  // More ride types: every type, searchable, in its group (RIDE-TYPE-ORGANISE; lib/rideTypeGroups.test.ts).
  assert.match(appFile, /<RideGroupChips preset=\{preset\} onPick=\{pickRide\} open=\{view === "ride"\} \/>/);
  // A pick goes through the ride type dialog's own choice, with Mountain Bike's loop (mtbChosen).
  assert.match(appFile, /choosePreset\(id, mtbChosen\(preset, id, chooseRideType\(id, carries\(id\) \? "cargo" : null, dials\)\)\);/);
  // Toggle buttons with their state, not colour alone.
  assert.match(src("../app/Sheets.tsx"), /className="chip ride-type-chip"\s+aria-pressed=\{preset === id\}/);
});

test("Go's places are Home, Eat, Water and Restroom (Work only in Favorites); Home works signed out", () => {
  // Signed in, Favorites takes Home's place (lib/favoritePlaces.test.ts), and Work is its second row, not a chip.
  const row = go.slice(go.indexOf('aria-label={t("Places")}'), go.indexOf('aria-label={t("More places")}'));
  const chips = [...row.matchAll(/<Icon name="(\w+)" size=\{18\} \/>\s*\{t\("(\w+)"\)\}\s*<\/button>/g)].map((m) => m[2]);
  assert.deepEqual(chips.slice(0, 4), ["Home", "Eat", "Water", "Restroom"]);
  assert.match(row, /\{FAVORITES_TEXT\}/);
  assert.doesNotMatch(row, /Work/);
  assert.ok("work" in ICON_PATHS, "Work's icon, in the Favorites popout");
  // The hint is the chip's description only while the Home sheet is shut (lib/homeSet.ts: the sheet replaces it).
  assert.match(go, /aria-describedby=\{places\.homeReady \|\| homeShown \? undefined : homeHint\}/);
  assert.match(go, /\{HOME_NOT_SET\}/);
  assert.doesNotMatch(go, /Sign in/);
  // Was /My Go/: since "Setting Home simply" the chip sets Home in place, so the line points at the chip.
  assert.match(HOME_NOT_SET, /tap Home/);
  assert.match(appFile, /homeReady: myGo\.home !== null,/);
  // Without a Home, the chip opens Go's Home sheet in place (was: My Go in Settings); with one, it rides there.
  assert.match(go, /onClick=\{\(event\) => \(places\.homeReady \? places\.onHome\(event\.currentTarget\) : setHomeOpen\(!homeOpen\)\)\}/);
  assert.match(appFile, /if \(!home\) return;[\s\S]*?void goTo\(home\.point, home\.label \|\| "Home"\);/);
  // Water and Restroom search from the rider's location, in their own sheet.
  assert.match(appFile, /onWater: \(chip\) => \{\s*openView\("nearest", chip\);\s*findNearestHere\("water"\);/);
  assert.match(appFile, /onRestroom: \(chip\) => \{\s*openView\("nearest", chip\);\s*findNearestHere\("restroom"\);/);
});

test("Go's Where to? is the destination from the rider's location, in one edit, with the loop off; without a location it keeps the destination and asks for a start", () => {
  const routeGo = appFile.slice(appFile.indexOf("const routeGo = ("), appFile.indexOf("const routeGoRef"));
  assert.match(routeGo, /commit\(\[start, \.\.\.vias, dest\], ride\.dials\.loop \? \{ \.\.\.ride, dials: \{ \.\.\.ride\.dials, loop: false \} \} : undefined\);/);
  const goTo = appFile.slice(appFile.indexOf("const goTo = async"), appFile.indexOf("const goToPlace"));
  assert.match(goTo, /const action = goPickAction\(pointsRef\.current, goStartRef\.current\);/);
  // Never the destination alone (it would become the start), and never dropped while the location is found.
  assert.doesNotMatch(goTo, /commit\(\[dest\]/);
  assert.match(goTo, /goPending\.current = \{ dest, name, vias, pressed, said: pressed && action\.kind === "wait" \};\s*if \(action\.kind === "wait"\) \{\s*if \(pressed\) setNoticeSaying\(goDestinationLocating\(name\), goPressLocatingSaid\(name\)\);\s*else setNotice\(goDestinationLocating\(name\)\);/);
  // A look-up's answer settles the destination waiting on it, only while the plan has no start (a start typed during
  // a slow look-up is routed from; no "To X. Current location not available" after it; review after #127).
  assert.match(goTo, /const settleGoWaiting = \(result: LocateResult, reason = false\) => \{\s*goAwaiting\.current = false;\s*const pending = goPending\.current;\s*if \(!result\.ok \|\| !insideCoverage\(result\.fix\.point\)\) \{\s*setGoStart\(\{ kind: "none" \}\);\s*if \(pending && pointsRef\.current\.length === 0\) \{\s*const why = reason && !result\.ok \? result\.reason : null;\s*const shown = why \? goDestinationNeedsStartBecause\(pending\.name, why\) : goDestinationNeedsStart\(pending\.name\);\s*if \(pending\.pressed\) setNoticeSaying\(shown, why \? goPressNeedsStartBecause\(pending\.name, why\) : goPressNeedsStartSaid\(pending\.name\)\);\s*else setNotice\(shown\);\s*\}\s*return;\s*\}\s*setHere\(result\.fix\);\s*setGoStart\(goHereStart\(result\.fix\.point\)\);\s*clearGoPending\(\);\s*if \(pending && pointsRef\.current\.length === 0\) routeGo\(result\.fix\.point, true, pending\.dest, pending\.name, !!pending\.pressed && !pending\.said, pending\.vias\);/);
  assert.match(goTo, /if \(!insideCoverage\(dest\)\) \{\s*setNotice\(OUTSIDE_NOTICE\);\s*return;/);
  // The opening look-up routes a destination picked while it ran; a start typed in routes one picked before it.
  assert.match(appFile, /if \(pending\) \{\s*clearGoPending\(\);\s*routeGoRef\.current\(result\.fix\.point, true, pending\.dest, pending\.name, !!pending\.pressed && !pending\.said, pending\.vias\);/);
  const startPick = appFile.slice(appFile.indexOf("const goStartPick = "), appFile.indexOf("const routeGo = ("));
  assert.match(startPick, /if \(pending\) \{\s*clearGoPending\(\);\s*routeGo\(point, false, pending\.dest, pending\.name, false, pending\.vias\);/);
});

test("the Go/Plan switch: toggle buttons in a named group (Review too for an admin), in Go's bar and Plan's header; a press is remembered as My Go's Open in", () => {
  assert.match(go, /role="group" aria-label=\{MODE_SWITCH_NAME\} aria-describedby=\{hintId\}/);
  assert.match(go, /className="mode-button" aria-pressed=\{mode === m\} onClick=\{\(\) => onChange\(m\)\}/);
  assert.match(appFile, /\{!goMode && <ModeSwitch mode=\{mode\} onChange=\{changeMode\} className="panel-mode" modes=\{switchModes\(canReview\)\} \/>\}/);
  assert.match(appFile, /<GoTopBar\s+mode=\{mode\}\s+onMode=\{changeMode\}\s+modes=\{switchModes\(canReview\)\}/);
  // Go's switch offers an admin's Review too, the same views as Plan's (Stephen 2026-10-17).
  assert.match(go, /<ModeSwitch mode=\{mode\} onChange=\{onMode\} modes=\{modes\} \/>/);
  const change = appFile.slice(appFile.indexOf("const changeMode = "), appFile.indexOf("// \"Copy link\""));
  assert.match(change, /writeTabMode\(next\);/);
  assert.match(change, /announceExtra\(modeSaid\(next\)\);/, "extra narration: said at Full, not at Brief");
  assert.doesNotMatch(change, /openIn/, "a switch is kept for the tab only, not saved as an Open in");
  // A save waits for the account's My Go to be read, so a Home is never overwritten by an early save.
  // (Since "Setting Home simply" the early return also tells a Home save it was not kept, so it can say so.)
  assert.match(appFile, /if \(meRef\.current\.signed_in\) \{\s*if \(!accountMyGoRead\.current\) \{\s*onSaved\?\.\(false\);\s*return;/);
});

// ---- the route summary (the owner's choices 4, 5 and 8) --------------------------------------

test("the warning line counts the facility notices on the same three conditions FacilityBreakdown shows them", () => {
  const quiet = { preset: "default", dials: startDials("default"), stress_m: { 1: 1000 }, hills_seek: null, hills_tolerate: null } as never;
  assert.equal(facilityNoticeCount(quiet), 0);
  const avoid = { preset: "default", dials: startDials("default"), stress_m: { 1: 1000, 5: 200 }, hills_seek: null, hills_tolerate: null } as never;
  assert.equal(facilityNoticeCount(avoid), 1);
  assert.equal(warningsLabel(1, true), "1 more warning");
  assert.equal(warningsLabel(2, true), "2 more warnings");
  assert.equal(warningsLabel(1, false), "1 warning");
  assert.equal(warningsLabel(3, false), "3 warnings");
});

test("the Avoid notice is one line: the first junction and how many more, with Avoid it's extra distance", () => {
  assert.equal(avoidLine({ avoid_junctions: [{ name: "Main St and 1st Ave" }] } as never), "Avoid junction: Main St and 1st Ave");
  assert.equal(avoidLine({ avoid_junctions: [{ name: "A" }, { name: "B" }, { name: "C" }] } as never), "Avoid junction: A and 2 more");
  assert.equal(avoidOfferShort({ avoid_alternate: { extra_distance_m: 1609 } } as never), "+1.0 mi (1.6 km)");
  assert.equal(avoidOfferShort({ avoid_alternate: { extra_distance_m: 50 } } as never), null);
  assert.equal(avoidOfferShort(null), null);
  // The whole sentence is still read: the short line is hidden from the reader, the sentence is not.
  const notice = src("../AvoidNotice.tsx");
  assert.match(notice, /role="alert"/);
  assert.match(notice, /<span className="visually-hidden">\{sentence\}<\/span>/);
});

test("a route's notes are one line each with an icon; their full words are in Info (the owner's choice 5)", () => {
  assert.match(app, /<li key=\{note\.key\} className=\{`note-line \$\{note\.className\}`\}>\s*<Icon name=\{note\.icon\} size=\{16\} \/>\s*<span className="note-text">\{note\.text\}<\/span>/);
  assert.match(app, /\{notes\.map\(\(note\) => \(\s*<p key=\{note\.key\} className="hint note-full">/);
  // The four quick figures are in Stress and facilities (choice 4); Share as image and Keep for offline behind More
  // (choice 8; Share itself is in the Route file sheet since v0.9.0).
  assert.match(app, /\{\/\* The four quick figures, first in the fold \(the owner's choice 4\)\. \*\/\}\s*<QuickFigures/);
  assert.match(app, /<div id=\{moreId\} className="route-more-body" hidden=\{!more\}>[\s\S]*?share-image[\s\S]*?keep-offline/);
});

// ---- Ride mode's 311 button (the owner's choice 9) and the text-size icon (choice 11, Large text's button since 2026-10-20) ----------------------

test("the 311 button shows anywhere on the route; its menu has the six problems in the owner's words and order", () => {
  assert.equal(ride311Shown({ off: false, progressM: 100 }), true, "inside DC or out: the log works everywhere (2026-10-20)");
  assert.equal(ride311Shown({ off: true, progressM: 100 }), false, "off the route there is no place to log");
  assert.equal(ride311Shown({ off: false, progressM: null }), false, "no place yet");
  assert.ok(RIDE_311_NAME.includes(RIDE_311_TEXT), "the visible words are in its name");
  const picked: string[] = [];
  const html = renderToStaticMarkup(createElement(Ride311Menu, { id: "m", open: true, place: { words: "on R St NW near 17th St NW", point: [-77.0389, 38.9126] }, onPick: (k) => picked.push(k), onClose: () => {} }));
  assert.match(html, /^<div id="m" class="ride-311-menu" role="group" aria-labelledby="m-heading">/);
  assert.match(html, /<h3 id="m-heading" tabindex="-1">Log for 311<\/h3><button type="button" class="secondary ride-311-close">Close<\/button>/);
  assert.match(html, /On R St NW near 17th St NW, GPS 38\.91260, -77\.03890\./);
  assert.equal(menuPlaceLine({ words: null, point: [-77.0389, 38.9126] }), "GPS 38.91260, -77.03890.", "no words: the coordinates alone");
  assert.doesNotMatch(menuPlaceLine({ words: "on an unnamed path", point: [-77.0389, 38.9126] }), /Near|miles/);
  const labels = [...html.matchAll(/class="ride-311-kind">(?:<svg[\s\S]*?<\/svg>)?([^<]+)<\/button>/g)].map((m) => m[1]);
  assert.deepEqual(labels, ["Pothole", "Downed tree", "Vehicle parked in a bike lane", "Roadway or bikeway obstructed", "Streetlight out", "Something else"]);
  assert.deepEqual(labels, REPORT_KINDS.map((k) => k.label));
  assert.match(renderToStaticMarkup(createElement(Ride311Menu, { id: "m", open: false, place: null, onPick: () => {}, onClose: () => {} })), /hidden=""/);
  // RideMode: the button only when shown, a disclosure; a pick closes the menu and logs the problem.
  assert.match(ride, /\{show311 && \(/);
  assert.match(ride, /aria-label=\{RIDE_311_NAME\}\s+aria-expanded=\{menu311\}\s+aria-controls=\{menu311Id\}/);
  assert.match(ride, /const pick311 = \(kind: ReportKind\) => \{\s*setMenu311\(false\);\s*button311\.current\?\.focus\(\);/);
  assert.doesNotMatch(ride, /className="fold ride-report"/, "no note fold after a pick (2026-10-21)");
  assert.match(ride, /if \(event\.key === "Escape" && menu311\) \{\s*event\.preventDefault\(\);\s*close311\(\);/);
  // About 60 px round, in the side buttons on the right edge (the owner, 2026-10-17).
  const css = src("../styles.css");
  assert.match(css, /\.ride-311-button \{\s*width: 60px;\s*height: 60px;/);
  assert.match(css, /\.ride-rail \{\s*position: absolute;\s*right: 12px;/);
});

test("Large text: a side button and Settings' switch, one choice; it replaced Big text (the owner, 2026-10-20)", () => {
  // "It actually should have it's own button"; Big text went: "if you can fit the largest text in the half mode, then you're not gaining much".
  assert.match(ride, /className="ride-round ride-text-size"\s+onClick=\{cycleText\}\s+aria-keyshortcuts="T"\s+aria-pressed=\{textSize === "large"\}\s+aria-label=\{RIDE_TEXT_BUTTON\}/);
  // The change is said, as Where am I? is.
  assert.match(ride, /announcer\.current\?\.answer\(said\);/);
  assert.doesNotMatch(ride, /BigTextField|ride-big/);
  const sheets = src("../app/Sheets.tsx");
  assert.match(sheets, /<SettingRow infoId="settings-big-text-info" about="large text" info=\{RIDE_TEXT_HELP\}/);
  assert.match(sheets, /role="switch"[^>]*aria-checked=\{props\.rideText\.size === "large"\}/s);
  const css = src("../styles.css");
  assert.match(css, /\.ride-large \.cue-card \{[^}]*height: 50%;/);
  assert.doesNotMatch(css, /\.riding-big|\.ride-big/);
  // The turn fills the card (RideMode sets --cue-fit), the small print 16 pt or more.
  assert.match(ride, /set\("--cue-fit-d", distance\);/);
  assert.match(css, /\.ride-large \.ride-togo,[^{]*\{\s*font-size: 16pt;/);
});

// ---- Go's start: the rider's current location by default (the owner, 2026-10-11 19:53 UTC) ----

test("go start: the location is asked for only in Go, once, and only while the plan has no point (a link's start wins)", () => {
  assert.equal(shouldAskGoStart({ mode: "go", asked: false, pointCount: 0 }), true);
  assert.equal(shouldAskGoStart({ mode: "plan", asked: false, pointCount: 0 }), false, "never in Plan");
  assert.equal(shouldAskGoStart({ mode: "go", asked: true, pointCount: 0 }), false, "once per page");
  assert.equal(shouldAskGoStart({ mode: "go", asked: false, pointCount: 1 }), false, "a start from the link wins");
});

test("go start: the line says the location, a typed or tapped start in its place, or that there is none", () => {
  const here = { kind: "here", point: [-77.03, 38.9], at: Date.now() } as const;
  assert.equal(goStartLine(here, null), "Start: your current location");
  assert.equal(GO_START_SAID, "Start: your current location.");
  assert.equal(goStartLine(here, "Union Station"), "Start: Union Station", "a typed or tapped start replaces it");
  assert.equal(goStartLine({ kind: "locating" }, null), "Start: finding your location…");
  assert.equal(goStartLine({ kind: "none" }, null), "Start: none yet; type a start");
  assert.equal(GO_START_UNAVAILABLE, "Current location not available; type a start.");
});

test("go start: a destination routes from the plan's first point, else from the location found, else asks", () => {
  const here = { kind: "here", point: [-77.03, 38.9], at: Date.now() } as const;
  assert.deepEqual(goRouteStart([], here), { point: [-77.03, 38.9], located: true });
  assert.deepEqual(goRouteStart([[-77.0, 38.89]], here), { point: [-77.0, 38.89], located: false }, "typed, tapped or from the link");
  assert.equal(goRouteStart([], { kind: "none" }), null);
  assert.equal(goRouteStart([], { kind: "locating" }), null);
});

test("go pick: route from the start Go has, wait while the location is found, else look it up (review of PR #95)", () => {
  const here = { kind: "here", point: [-77.03, 38.9], at: Date.now() } as const;
  assert.deepEqual(goPickAction([], here), { kind: "route", point: [-77.03, 38.9], located: true });
  assert.deepEqual(goPickAction([[-77.0, 38.89]], { kind: "none" }), { kind: "route", point: [-77.0, 38.89], located: false });
  assert.deepEqual(goPickAction([], { kind: "locating" }), { kind: "wait" }, "a pick while the location is found is kept, not dropped");
  assert.deepEqual(goPickAction([], { kind: "none" }), { kind: "locate" });
  assert.deepEqual(goPickAction([], { kind: "idle" }), { kind: "locate" });
  assert.equal(goDestinationNeedsStart("Union Station"), "To Union Station. Current location not available; type a start.");
  assert.match(goDestinationLocating("Union Station"), /^To Union Station: finding your location/);
});

test("go tap: a press on the map in Go is the destination, routed as a picked one is (the owner, 2026-10-12)", () => {
  assert.equal(goTapSetsEnd("go"), true);
  assert.equal(goTapSetsEnd("plan"), false, "Plan's presses add points as before");
  assert.equal(goDestinationSet("38.9055, -77.0365"), "Destination set: 38.9055, -77.0365.");
  assert.equal(goTapRoutedSaid("Union Station", true, false), "Destination set: Union Station.", "Brief: the destination only");
  assert.equal(goTapRoutedSaid("Union Station", true, true), "Destination set: Union Station. Planning a route from your location.");
  assert.equal(goTapRoutedSaid("Union Station", false, true), "Destination set: Union Station. Planning a route from your start.");
  // App: the press (and Map tools' button, which places through it) goes to goTo as a pressed destination, after the
  // area check and before the points limit (Go replaces the destination, it never adds a point); no tap is a start.
  const place = appFile.slice(appFile.indexOf("const place = useCallback("), appFile.indexOf("// \"Use my location\": one look-up"));
  assert.match(place, /if \(goTapSetsEnd\(modeRef\.current\)\) \{\s*void goToRef\.current\(point, goPlaceName\(namer\.name\(point\)\?\.name, point\), true\);\s*return;\s*\}/);
  // The same name on the sheet's "To …": the place name once looked up, else the coordinates that were said (review of #116).
  assert.equal(goPlaceName(undefined, [-77.0365, 38.9055]), "38.9055, -77.0365");
  assert.equal(goPlaceName("Dupont Circle", [-77.0434, 38.9096]), "Dupont Circle");
  assert.match(appFile, /destination=\{points\.length > 0 \? goPlaceName\(namer\.name\(points\[points\.length - 1\]\)\?\.name, points\[points\.length - 1\]\) : null\}/);
  assert.doesNotMatch(appFile, /\?\? "Destination"/);
  assert.ok(place.indexOf("goTapSetsEnd") > place.indexOf("if (!insideCoverage(point))"), "a press outside the area is refused first");
  assert.ok(place.indexOf("goTapSetsEnd") < place.indexOf("MAX_POINTS"), "Go's press is never refused for the points limit");
  assert.doesNotMatch(place, /goPending/, "a press is never the start of a waiting destination now");
  assert.match(appFile, /const modeRef = useRef\(mode\);\s*modeRef\.current = mode;/);
  assert.match(appFile, /const goToRef = useRef\(goTo\);\s*goToRef\.current = goTo;/);
  assert.match(appFile, /const addAtCentre = \(\) => \{[\s\S]*?place\(\[lng, lat\]\);/);
  // Said: routed at once, "Destination set" (with the planning at Full); waiting for a start, "Destination set" and
  // what it waits for in one announcement (said apart, the notice replaced it about 140 ms later; review of #127).
  assert.match(appFile, /if \(pressed\) announce\(goTapRoutedSaid\(name, located, saysExtra\(announceLevelNow\.current\)\)\);\s*else announceExtra\(/);
  assert.equal(goPressLocatingSaid("38.9055, -77.0365"), "Destination set: 38.9055, -77.0365. Finding your location for the start…");
  assert.equal(goPressNeedsStartSaid("38.9055, -77.0365"), "Destination set: 38.9055, -77.0365. Current location not available; type a start.");
  assert.doesNotMatch(appFile, /announce\(goDestinationSet\(/, "never said alone before a notice that would replace it");
  // The notice shown with it is not said again on its own (it would replace the fuller line).
  assert.match(appFile, /const setNoticeSaying = \(shown: string, said: string\) => \{\s*noticeSaidAs\.current = shown;\s*setNotice\(shown\);\s*announce\(said\);/);
  // No location yet (Go's start none or idle): a look-up that is slow (a timeout takes up to a minute) or already under
  // way (locateForGo answers null) does not leave the press unsaid. Said with "Finding your location…" once the look-up
  // has run GO_PRESS_LOCATING_SAY_MS, or at once on null, and only once; a quick denial is said alone (review of #127).
  assert.ok(GO_PRESS_LOCATING_SAY_MS > 0 && GO_PRESS_LOCATING_SAY_MS <= 1500, "a timeout is never left silent for long");
  const locatePath = appFile.slice(appFile.indexOf("const mine = goPending.current;"), appFile.indexOf("setHere(result.fix);", appFile.indexOf("const mine = goPending.current;")));
  assert.match(locatePath, /const sayLocating = \(\) => \{\s*if \(!mine \|\| goPending\.current !== mine \|\| mine\.said\) return;\s*mine\.said = true;\s*setNoticeSaying\(goDestinationLocating\(name\), goPressLocatingSaid\(name\)\);\s*\};/);
  assert.match(locatePath, /const slow = pressed \? window\.setTimeout\(sayLocating, GO_PRESS_LOCATING_SAY_MS\) : undefined;\s*const result = await locateForGo\(\);\s*window\.clearTimeout\(slow\);/);
  assert.match(locatePath, /if \(result === null\) \{[\s\S]*?if \(pressed\) sayLocating\(\);\s*goAwaiting\.current = true;\s*return;\s*\}\s*settleGoWaiting\(result\);/);
  // The gate busy: the look-up under way settles the destination when it answers, whoever asked for it (review after
  // #127: Go's Locate, Use my location and the nearest finder left a press told "Finding…" and never routed it).
  assert.match(appFile, /const goLocate = async \(\) => \{\s*const result = await locateForGo\(\);\s*if \(result === null\) return;\s*\/\/[^\n]*\n\s*\/\/[^\n]*\n\s*if \(goWaiting\(\)\) \{\s*settleGoWaiting\(result, true\);\s*return;\s*\}/);
  assert.match(appFile, /if \(!gate\.finish\(press\)\) return;\s*setLocating\(false\);\s*\/\/[^\n]*\n\s*if \(goWaitingRef\.current\(\)\) \{\s*goSettleRef\.current\(result\);\s*return;\s*\}/, "Use my location");
  assert.match(appFile, /gate\.finish\(press\);\s*setLocating\(false\);\s*\/\/[^\n]*\n\s*if \(goWaitingRef\.current\(\)\) goSettleRef\.current\(result\);\s*return result;/, "the nearest finder");
  assert.match(appFile, /const goWaiting = \(\) => goAwaiting\.current && goPending\.current !== null && modeRef\.current === "go";/);
  // A stale wait never silences Locate (review of #128): whenever the waiting destination goes (routed, a start typed,
  // leaving Go), the wait goes with it; only the clear itself writes goPending to null.
  assert.match(appFile, /const clearGoPending = \(\) => \{\s*goPending\.current = null;\s*goAwaiting\.current = false;\s*\};/);
  assert.equal((appFile.match(/goPending\.current = null;/g) ?? []).length, 1, "every other clear goes through clearGoPending");
  assert.match(appFile, /if \(action\.kind === "route"\) \{\s*clearGoPending\(\);/);
  // Leaving Go drops the destination it kept, and its notice with it (re-check of #128), from the switch (the
  // account's Open in, which could also leave Go, was dropped on 2026-10-22).
  assert.match(appFile, /const leaveGo = \(\) => \{\s*if \(goPending\.current\) setNotice\(null\);\s*clearGoPending\(\);\s*\};/);
  assert.match(appFile, /setModeState\(next\);\s*if \(next !== "go"\) leaveGo\(\);/, "the Go/Plan switch");
  assert.doesNotMatch(appFile, /now === later/, "an account read never moves the view");
  // Locate's answer to a waiting destination keeps its reason (review of #128).
  assert.match(appFile, /if \(goWaiting\(\)\) \{\s*settleGoWaiting\(result, true\);\s*return;\s*\}/);
  assert.equal(goStartFailedReason("denied"), "Your location is blocked for this site. Allow location in the browser's site settings, or type a start.");
  assert.equal(goStartFailedReason("unavailable"), "Your location could not be found right now. Try again, or type a start.");
  assert.equal(goStartFailedReason("timeout"), "Finding your location took too long. Try again, or type a start.");
  assert.equal(goStartFailedReason("unsupported"), "This browser cannot share your location. Type a start instead.");
  assert.equal(goStartFailedReason("insecure"), "Your location can only be used on a secure (HTTPS) page. Type a start instead.");
  assert.equal(goDestinationNeedsStartBecause("Union Station", "denied"), "To Union Station. Your location is blocked for this site. Allow location in the browser's site settings, or type a start.");
  assert.equal(goPressNeedsStartBecause("38.9055, -77.0365", "timeout"), "Destination set: 38.9055, -77.0365. Finding your location took too long. Try again, or type a start.");
  // Go's opening look-up settles a destination that waited on it itself.
  assert.match(appFile, /setGoStart\(\{ kind: "idle" \}\);\s*return;\s*\}\s*\/\/[^\n]*\n\s*goAwaiting\.current = false;\s*const pending = goPending\.current;/);
  // Located later (a look-up that answers after the press), the pressed destination is routed and said as a press is.
  assert.match(appFile, /routeGo\(result\.fix\.point, true, pending\.dest, pending\.name, !!pending\.pressed && !pending\.said, pending\.vias\);/);
  // Map tools in Go: the same button, named for what it does, and never disabled by the points limit.
  assert.match(appFile, /addDisabled=\{!goTapSetsEnd\(mode\) && points\.length >= MAX_POINTS\}\s*setsEnd=\{goTapSetsEnd\(mode\)\}/);
  assert.match(src("../MapTools.tsx"), /\{setsEnd \? SET_END_AT_CENTRE_LABEL : ADD_AT_CENTRE_LABEL\}/);
});

test("go start: App asks once when Go opens, says the start politely, and says when it is not available", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /if \(!shouldAskGoStart\(\{ mode, asked: goStartAsked\.current, pointCount: pointsRef\.current\.length \}\)\) return;/);
  assert.match(app, /if \(pointsRef\.current\.length > 0\) return;[\s\S]{0,300}?\} else \{\s*\/\/[^\n]*\n\s*flyToInView\(result\.fix\.point, 15\);\s*announce\(GO_START_SAID\);\s*\}/);
  assert.match(app, /if \(pointsRef\.current\.length === 0\) \{\s*if \(pending\?\.pressed\) setNoticeSaying\(goDestinationNeedsStart\(pending\.name\), goPressNeedsStartSaid\(pending\.name\)\);\s*else setNotice\(pending \? goDestinationNeedsStart\(pending\.name\) : GO_START_UNAVAILABLE\);/);
  // Go offers the routes to choose from at once; Plan keeps its fold.
  const panel = readFileSync(new URL("../app/RoutePanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /const \[routesOpen, setRoutesOpen\] = useState\(mode === "go"\);/);
});

// ---- Announcements, Brief or Full (the owner, 2026-10-11 20:23 UTC) ----
import { ANNOUNCE_KEY, announceLevel, readAnnounceChoice, saysExtra, writeAnnounceChoice } from "./announceLevel.ts";

test("announcements: unset, Go is brief and Plan is full; a choice holds in both, and is kept on this device", () => {
  assert.equal(announceLevel("", "go"), "brief");
  assert.equal(announceLevel("", "plan"), "full");
  assert.equal(announceLevel("full", "go"), "full");
  assert.equal(announceLevel("brief", "plan"), "brief");
  assert.equal(saysExtra("brief"), false);
  assert.equal(saysExtra("full"), true);
  const kept = new Map<string, string>();
  const store = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
  assert.equal(readAnnounceChoice(store), "");
  writeAnnounceChoice("full", store);
  assert.equal(kept.get(ANNOUNCE_KEY), "full");
  assert.equal(readAnnounceChoice(store), "full");
  kept.set(ANNOUNCE_KEY, "loud");
  assert.equal(readAnnounceChoice(store), "", "anything else is unset");
});

test("announcements: the essentials are always said; only the narration is extra", () => {
  const app = appSource();
  for (const extra of ["announceExtra(FINDING_LOCATION);", "announceExtra(modeSaid(next));", "announceExtra(`${presetSaid(id)}.`);", 'announceExtra("The map is at your location.");'])
    assert.ok(app.includes(extra), extra);
  // The start Go found, and when it could not, are essentials.
  assert.match(app, /announce\(GO_START_SAID\)/);
  assert.match(app, /setNotice\(pending \? goDestinationNeedsStart\(pending\.name\) : GO_START_UNAVAILABLE\)/);
  // Go and Plan both start the ride at once (the owner, 2026-10-24): no first-ride question.
  assert.match(app, /const startRide = \(unlocked = false\) => \{[^}]*beginRide\(ridePrefs, unlocked\);\s*\};/);
  assert.doesNotMatch(app, /setRideAsk|ride-ask/);
});

test("go start: a location found long ago is looked up again before a destination routes from it (the owner, 2026-10-19)", () => {
  const found = 1_000_000;
  const here = goHereStart([-77.03, 38.9], found);
  assert.deepEqual(here, { kind: "here", point: [-77.03, 38.9], at: found });
  assert.equal(goStartStale(here, found + GO_START_MAX_AGE_MS), false, "fresh up to the limit");
  assert.deepEqual(goPickAction([], here, found + 60_000), { kind: "route", point: [-77.03, 38.9], located: true });
  // An hour later (the app left open since an earlier ride): not routed from; looked up again.
  assert.equal(goStartStale(here, found + 60 * 60_000), true);
  assert.equal(goRouteStart([], here, found + 60 * 60_000), null);
  assert.deepEqual(goPickAction([], here, found + 60 * 60_000), { kind: "locate" });
  assert.equal(goStartStale(here, found - 1), true, "a clock set back is not trusted");
  // A start in the plan (typed, tapped or from the link) is never stale: it is not the location.
  assert.deepEqual(goPickAction([[-77.0, 38.89]], here, found + 60 * 60_000), { kind: "route", point: [-77.0, 38.89], located: false });
  assert.equal(goStartStale({ kind: "none" }), false);
});

test("go start: Go looks a stale start up again when the page comes back into view", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /document\.addEventListener\("visibilitychange", onVisible\)/);
  assert.match(app, /if \(!goStartStale\(goStartRef\.current\)\) return;/);
  assert.doesNotMatch(app, /setGoStart\(\{ kind: "here"/, "every found start is stamped (goHereStart)");
});

test("go pick: a destination set in Go routes from a fresh fix once the rider has moved (the owner, 2026-10-19)", () => {
  const prior: [number, number] = [-77.07, 38.905];
  assert.deepEqual(goPickStart(prior, null), { point: prior, moved: false }, "no fix in time: the start Go had (under 2 min old)");
  assert.deepEqual(goPickStart(prior, { point: [-77.0701, 38.905] }), { point: prior, moved: false }, "about 9 m: not moved, the early route still matches");
  assert.deepEqual(goPickStart(prior, { point: [-76.99, 38.91] }), { point: [-76.99, 38.91], moved: true });
  assert.deepEqual(goPickStart(prior, { point: [-80, 38.9] }), { point: prior, moved: false }, "a fix outside the map is not the start");
  assert.equal(GO_PICK_MOVED_M, 25);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const goTo = app.slice(app.indexOf("const goTo = async"), app.indexOf("const settleGoWaiting"));
  assert.match(goTo, /const fix = await goPickFix\(\);\s*window\.clearTimeout\(slow\);\s*\/\/[^\n]*\n\s*if \(pick !== goPickSeq\.current \|\| pointsRef\.current\.length > 0 \|\| modeRef\.current !== "go"\) return;\s*routeGo\(goPickStart\(action\.point, fix\)\.point, true, dest, name, pressed && !said, vias\);/);
  // The look-up is bounded and settles a destination waiting on the gate, as every look-up does.
  const fix = app.slice(app.indexOf("const goPickFix"), app.indexOf("const goTo = async"));
  assert.match(fix, /window\.setTimeout\(\(\) => resolve\(null\), GO_PICK_LOOK_MS\)/);
  assert.match(fix, /if \(result && goWaitingRef\.current\(\)\) \{\s*goSettleRef\.current\(result\);/);
  // The tap still looks the location up for its destination (above); a warm look-up made while the rider was in
  // Where to? only makes that look-up quick (routing audit S28). The tap never waits on the warm one.
  assert.doesNotMatch(goTo, /goWarm/);
});

test("go warm look-up: Where to? focused or an early start fired refreshes a location over 20 s old, quietly (routing audit S28)", () => {
  assert.equal(GO_WARM_AFTER_MS, 20_000);
  const found = 1_000_000;
  const here = goHereStart([-77.07, 38.905], found);
  assert.equal(goWarmDue(here, null, found + 5_000), false, "a fix 5 s old is fresh enough");
  assert.equal(goWarmDue(here, null, found + GO_WARM_AFTER_MS), true);
  assert.equal(goWarmDue(here, null, found + 90_000), true);
  assert.equal(goWarmDue(here, null, found + 5 * 60_000), true, "a stale start is warmed too");
  assert.equal(goWarmDue(here, found + 25_000, found + 30_000), false, "one warm look-up per 20 s, however often the box is focused");
  assert.equal(goWarmDue(here, found + 25_000, found + 45_000), true);
  assert.equal(goWarmDue(here, null, found - 1), true, "a clock set back is not trusted");
  for (const start of [{ kind: "idle" }, { kind: "locating" }, { kind: "none" }] as const) {
    assert.equal(goWarmDue(start, null, found), false, `no warm look-up with no location (${start.kind}): it would ask for permission`);
  }
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const warm = app.slice(app.indexOf("const goWarmFix = () => {"), app.indexOf("const goTo = async"));
  assert.match(warm, /if \(!goWarmDue\(goStartRef\.current, goWarmAt\.current, now\)\) return;\s*goWarmAt\.current = now;\s*void locate\(geoEnv\)\.then\(/);
  // Around the gate and `locating`: the locate button does not look busy and a Use my location press is not dropped.
  assert.doesNotMatch(warm, /gate\.|setLocating|locateForGo|announce/);
  assert.match(warm, /setGoStart\(goHereStart\(goPickStart\(was\.point, result\.fix\)\.point\)\)/);
  const early = app.slice(app.indexOf("const goEarlyToPlace = "), app.indexOf("const goAddStopAt = "));
  assert.match(early, /goEarlyTimer\.current = window\.setTimeout\(\(\) => \{\s*goWarmFix\(\);/);
  assert.match(app, /onTopPlace=\{goEarlyToPlace\}\s*onWhereToFocus=\{goWarmFix\}/);
  const go = readFileSync(new URL("../app/Go.tsx", import.meta.url), "utf8");
  assert.match(go, /<PlaceSearch variant="go"[^\n]*onFocusBox=\{onWhereToFocus\} \/>/);
  const search = readFileSync(new URL("../PlaceSearch.tsx", import.meta.url), "utf8");
  assert.match(search, /onFocus=\{\(event\) => \{\s*onFocusBox\?\.\(\);/);
});

test("Go's searches lean to the route's start and list places nearest it first, with distances (P2)", () => {
  // Where to?, the start box and Add a stop each sort by the start; Go's bias is the start, the map's view only without one.
  assert.match(go, /variant="go"[^\n]*bias=\{searchBias\} origin=\{searchOrigin\}/);
  assert.match(go, /variant="stop"[^\n]*bias=\{searchBias\} origin=\{searchOrigin\}/);
  assert.match(go, /variant="start"[\s\S]{0,160}origin=\{searchOrigin\}/);
  assert.match(appFile, /const goSearchBias = \(\): LonLat \| undefined => startBiasPoint\(goSearchOrigin\(\)\) \?\? searchBias\(\);/);
  assert.equal(appFile.match(/searchBias=\{goSearchBias\}\s+searchOrigin=\{goSearchOrigin\}/g)?.length, 2);
  // Plan's boxes sort by the first point.
  assert.match(src("../app/Planner.tsx"), /origin=\{\(\) => points\[0\]\}/);
  // The list is the sorted one, and Enter takes its first place.
  assert.match(src("../PlaceSearch.tsx"), /const places = nearestFirst\(found, start, answered\);/);
});
