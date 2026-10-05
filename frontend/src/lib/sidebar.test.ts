// The sidebar redesign (OWNER-DECISIONS 312, mockup v3): the Ride line's words, the quick figures,
// the bottom bar, the folds and the font. App.tsx and the components are not rendered by a test (no
// DOM here), so where they place things is read as source, as the other panels' wiring is.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { startDials, type Dials } from "./dials.ts";
import { hillsShort, rideSummary, rideSummarySpoken, trafficShort, whenShort } from "./rideSummary.ts";
import { NOT_AVAILABLE, calmPercent, heavyMetres, junctionFigure, quickFigures, stressBarKey, stressBarLabel } from "./quickFigures.ts";
import {
  BAR_ITEMS,
  COPY_LINK,
  MORE_TIPS,
  FEWER_TIPS,
  SHEET_TITLES,
  copyText,
  foldTitle,
  linkToCopy,
  rideActionLabel,
  searchLede,
  stepsCount,
} from "./sidebar.ts";
import { StressZoomNotes, ZOOM_LEVELS_LINK, CAR_FREE_NOTE } from "./stressLegend.ts";
import { sheetOrder } from "./sheet.ts";

const src = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");
const app = src("../App.tsx");
const sidebar = src("../Sidebar.tsx");
const css = src("../styles.css");

// ---- the Ride line ----------------------------------------------------------

test("the Ride line: the mockup's words for a Default ride, ride type first", () => {
  assert.equal(rideSummary("default", startDials("default")), "Default · quiet streets · balanced hills · now");
  assert.equal(rideSummarySpoken("default", startDials("default")), "Default, quiet streets, balanced hills, now");
});

test("the Ride line follows the sliders, the ride time, the loop and gravel; and names a moved ride Custom", () => {
  const dials: Dials = { ...startDials("default", null, "weekend"), stress: 100, hills: -90, loop: true, avoidGravel: true };
  assert.equal(
    rideSummary("default", dials),
    "Custom (based on Default) · calmest · avoids hills · weekend · loop · avoids gravel",
  );
  assert.equal(whenShort("weekday_rush"), "weekday rush");
  assert.equal(whenShort("weekday_offpeak"), "weekday off-hours");
  assert.equal(whenShort(null), "now");
});

test("every slider position has words, and Mass Ride's locked slider says what it is", () => {
  for (let stress = 0; stress <= 100; stress += 5) assert.ok(trafficShort(stress).length > 0);
  for (let hills = -100; hills <= 100; hills += 5) assert.ok(hillsShort(hills).length > 0);
  assert.match(rideSummary("mass-ride", startDials("mass-ride")), /^Mass Ride · most direct roadway · avoids hills · now$/);
  // A loop set on a Mass Ride is hidden there (374): the summary does not say it.
  assert.doesNotMatch(rideSummary("mass-ride", { ...startDials("mass-ride"), loop: true }), /loop/);
  // Cargo says its load.
  assert.match(rideSummary("cargo", startDials("cargo", "people")), /^Cargo Bike, cargo with passengers · /);
});

test("the Ride line never carries the rider and bike weight (313-314): not a figure, not the dial", () => {
  const withWeight: Dials = { ...startDials("default"), systemWeightKg: 123 };
  assert.equal(rideSummary("default", withWeight), rideSummary("default", startDials("default")));
  assert.doesNotMatch(rideSummary("default", withWeight), /123|lb|kg|weight/i);
  assert.doesNotMatch(src("./rideSummary.ts").replace(/\/\*[\s\S]*?\*\//g, ""), /systemWeight|weight/i);
});

test("the Ride line is a heading holding a button with aria-expanded, whose words are read with commas", () => {
  assert.match(sidebar, /<h2 id="ride-settings-heading" className="ride-line">\s*<button type="button" className="ride-line-button" aria-expanded=\{open\} aria-controls=\{bodyId\}/);
  assert.match(sidebar, /<span className="ride-line-summary" aria-hidden="true">/);
  assert.match(sidebar, /<span className="visually-hidden">: \{spoken\}\.<\/span>/);
  assert.equal(rideActionLabel(false), "Edit");
  assert.equal(rideActionLabel(true), "Done");
  // The controls stay in the page while closed, so nothing they hold is lost.
  assert.match(sidebar, /<div id=\{bodyId\} className="ride-settings-body" hidden=\{!open\}>/);
});

test("App puts the ride type and every dial behind the Ride line, in the mockup's order", () => {
  assert.match(app, /<RideSettings key="presets" summary=\{rideSummary\(preset, dials\)\} spoken=\{rideSummarySpoken\(preset, dials\)\}>\s*\{presetsSection\}\s*<DialsPanel/);
  const dials = src("../DialsPanel.tsx");
  const at = (text: string) => {
    const i = dials.indexOf(text);
    assert.ok(i > 0, text);
    return i;
  };
  const order = [
    'label="Traffic"',
    'label="Hills"',
    "<legend>When</legend>",
    "{view.target && (",
    "<WeightSetting",
    "{loop && (",
    "Avoid gravel",
  ].map(at);
  assert.deepEqual(order, [...order].sort((a, b) => a - b), "Traffic, Hills, When, target distance, weight, loop, gravel");
  // The weight row is the existing one: status only, Change opening the private dialog (weightDialog.ts).
  assert.match(dials, /import \{ WeightSetting \} from "\.\/lib\/weightDialog\.ts";/);
});

// ---- points first ------------------------------------------------------------

test("the points come first, the how-to is behind More tips, and Reverse, Undo and Clear share a row", () => {
  assert.equal(MORE_TIPS, "More tips");
  assert.equal(FEWER_TIPS, "Fewer tips");
  assert.match(searchLede("default", false), /^Search, or click the map: start, then end\./);
  assert.match(searchLede("default", true), /come[s]? back to the start/);
  assert.match(app, /<MoreTips>\s*<p className="hint">\{emptyPlanHint\(preset, loopVias\)\}<\/p>/);
  assert.match(sidebar, /aria-expanded=\{open\} aria-controls=\{id\}/);
  // Add point at map center first, then the compact row; every existing button is still there.
  const labels = ["Add point at map center", "Reverse", "Undo", "Redo", "Clear"].map((t) => app.indexOf(t, app.indexOf('className="actions point-add"')));
  assert.ok(labels.every((i) => i > 0));
  assert.deepEqual(labels, [...labels].sort((a, b) => a - b));
  assert.match(app, /ref=\{addRef\}/);
  assert.match(app, /aria-describedby=\{reverseHint \? "reverse-hint" : undefined\}/);
  assert.match(app, /<p className="hint" id="reverse-hint">/);
});

// ---- the route view ---------------------------------------------------------

const route = {
  stress_m: { "1": 6100, "2": 3000, "3": 800, "4": 100 },
  facility_m: { path: 3900, protected: 0, lane: 100, none: 5900 },
  intersections: [
    { severity: "red", m: 2600, reason: "x", name: "" },
    { severity: "orange", m: 4100, reason: "y", name: "" },
    { severity: "orange", m: 5300, reason: "z", name: "" },
    { severity: "orange", m: 7000, reason: "w", name: "" },
  ],
} as never;

test("the four quick figures: share on paths and quiet streets, heavy traffic, junctions, off-road path", () => {
  const [calm, heavy, junctions, path] = quickFigures(route);
  assert.deepEqual([calm.label, calm.value], ["Paths and quiet streets", "91%"]);
  assert.deepEqual([heavy.label, heavy.value], ["Heavy traffic", "330 ft (100 m)"]);
  assert.deepEqual([junctions.label, junctions.value], ["Stressful junctions", "1 very high, 3 higher"]);
  assert.deepEqual([path.label, path.value], ["Off-road path", "2.4 mi (3.9 km)"]);
});

test("a figure the planner did not send is said so, not guessed; none is 'None'", () => {
  const bare = quickFigures({} as never);
  assert.deepEqual(bare.map((f) => f.value), [NOT_AVAILABLE, NOT_AVAILABLE, NOT_AVAILABLE, NOT_AVAILABLE]);
  const calmRoute = quickFigures({ stress_m: { "1": 1000 }, facility_m: { path: 0 }, intersections: [] } as never);
  assert.deepEqual(calmRoute.map((f) => f.value), ["100%", "None", "None", "None"]);
  assert.equal(calmPercent({}), null);
  assert.equal(heavyMetres({ "4": 10, "5": 5 }), 15, "heavy traffic counts the roads best avoided too");
  assert.equal(junctionFigure(null), NOT_AVAILABLE);
  assert.equal(junctionFigure([{ severity: "orange" }] as never), "1 higher");
});

test("the stress bar is one image with each share in its name, and a line of text says the same", () => {
  const segments = [
    { short: "LTS 1", percent: 61 },
    { short: "LTS 2", percent: 30 },
    { short: "LTS 3", percent: 0 },
    { short: "LTS 4", percent: 9 },
  ];
  assert.equal(stressBarLabel(segments), "Traffic stress along the route: LTS 1 61 percent, LTS 2 30 percent, LTS 4 9 percent");
  assert.equal(stressBarKey(segments), "LTS 1 61% · LTS 2 30% · LTS 4 9%");
  assert.match(app, /<div className="stress-bar" role="img" aria-label=\{stressBarLabel\(segments\)\}>/);
  assert.match(app, /<p className="stress-key" aria-hidden="true">/);
});

test("the route's folds: Stress and facilities, Directions, Junctions to watch, Routes to choose from; no elevation chart yet", () => {
  assert.equal(foldTitle("Junctions to watch", 4), "Junctions to watch (4)");
  assert.equal(foldTitle("Stress and facilities", null), "Stress and facilities");
  assert.equal(stepsCount(1), "1 step");
  assert.equal(stepsCount(12), "12 steps");
  const at = (text: string) => {
    const i = app.indexOf(text, app.indexOf("function RouteSummary"));
    assert.ok(i > 0, text);
    return i;
  };
  const order = ['<Fold title="Stress and facilities">', "<RouteDescription route={route} fold />", 'foldTitle("Junctions to watch", junctions)', 'foldTitle("Routes to choose from", pickerCount)'].map(at);
  assert.deepEqual(order, [...order].sort((a, b) => a - b));
  assert.doesNotMatch(app, /Elevation and stress/, "the elevation chart is not in the app (322), so there is no section for it");
  assert.match(sidebar, /<details className=\{className \? `fold \$\{className\}` : "fold"\} open=\{open\}>\s*<summary>\{title\}<\/summary>/);
  // The notices stay in view; only the figures are folded.
  assert.match(app, /<FacilityBreakdown route=\{route\} part="notices" \/>/);
  assert.match(app, /<FacilityBreakdown route=\{route\} part="figures" \/>/);
});

test("GPX and Copy link are pinned under the scrolling part, outside it", () => {
  assert.equal(COPY_LINK, "Copy link");
  assert.equal(linkToCopy({ href: "https://x.test/#plan" }), "https://x.test/#plan");
  const scrollEnd = app.indexOf("</div>\n\n          {/* Pinned under");
  const pinned = app.indexOf('<div className="route-actions">');
  assert.ok(scrollEnd > 0 && pinned > scrollEnd, "outside .panel-scroll");
  assert.match(app, /onClick=\{\(\) => downloadGpx\(shown, routedPoints, routedLoop\)\}>\s*Download GPX/);
  assert.match(app, /<span role="status" className="visually-hidden">\s*\{linkSaid\}/);
  // The link is the address, which carries the plan and never the weight (313).
  assert.match(app, /copyText\(linkToCopy\(window\.location\), navigator\.clipboard, selectionCopy\)/);
});

test("copyText uses the clipboard, falls back to the selection method, and says false when both fail", async () => {
  const calls: string[] = [];
  assert.equal(await copyText("a", { writeText: async (t) => void calls.push(t) }, () => false), true);
  assert.deepEqual(calls, ["a"]);
  assert.equal(await copyText("b", {}, (t) => t === "b"), true);
  assert.equal(await copyText("c", { writeText: async () => Promise.reject(new Error("no")) }, () => true), true);
  assert.equal(await copyText("d", undefined, () => false), false);
  assert.equal(await copyText("e", undefined, () => { throw new Error("no"); }), false);
});

// ---- the bottom bar and its sheets ------------------------------------------------

test("the bottom bar is Map layers, Legend, GPX and About: real buttons, each with words", () => {
  assert.deepEqual(BAR_ITEMS.map((i) => i.label), ["Map layers", "Legend", "GPX", "About"]);
  assert.deepEqual(BAR_ITEMS.map((i) => i.opens), ["layers", "layers", "gpx", "about"]);
  assert.equal(BAR_ITEMS.filter((i) => i.toLegend).length, 1, "only Legend opens at the legend");
  assert.ok(BAR_ITEMS.every((i) => i.description.length > 0));
  assert.match(sidebar, /<nav aria-label="More" className="bottom-bar">/);
  assert.match(sidebar, /<button\s+key=\{item\.id\}\s+type="button"/);
  assert.match(sidebar, /<span>\{item\.label\}<\/span>/);
  assert.match(sidebar, /<svg[^>]*aria-hidden="true">\s*\{ICONS\[item\.id\]\}/);
  assert.doesNotMatch(sidebar, /<a /, "no link where a button is meant");
});

test("a sheet: Back is a labelled button, its heading takes the focus, Escape goes back", () => {
  assert.deepEqual(Object.values(SHEET_TITLES), ["Map layers", "GPX file", "About RouteMaker"]);
  assert.match(sidebar, /aria-label="Back to the planner"/);
  assert.match(sidebar, /<h2 id=\{`\$\{id\}-title`\} ref=\{headingRef\} tabIndex=\{-1\}>/);
  assert.match(sidebar, /event\.key !== "Escape"/);
  assert.match(app, /barButtons\.current\[openedBy\.current\]\?\.focus\(\)/);
  assert.match(app, /target\.current\?\.focus\(\)/);
});

test("the Map layers sheet holds the switches, the rail stations, federal land and the full legend", () => {
  const sheet = app.slice(app.indexOf('id="sheet-layers"'), app.indexOf('id="sheet-gpx"'));
  for (const part of ["<AccessibilitySwitch", "<HighStressLanesSwitch", "Show traffic stress on the map", "<RailStationsSection", "<FederalLandFor", "<StressLegend"]) {
    assert.ok(sheet.includes(part), part);
  }
  assert.match(sheet, /<StressLegend facilities=\{facilitiesShown\} zoom=\{zoom\} shown=\{stressVisible\} foldedZoom \/>/);
  assert.match(app, /id="sheet-gpx"[\s\S]*<GpxPanel/);
  assert.match(app, /federalVisible=\{federalShown\(preset, federalOn\)\}/, "federal land stays Mass Ride's (324)");
});

test("the zoom explanations are behind 'What each zoom level shows'; the zoom notice stays in view", () => {
  const folded = renderToStaticMarkup(createElement(StressZoomNotes, { zoom: 11, shown: true, folded: true }));
  assert.match(folded, /<p class="notice" role="status">Zoom in to see traffic stress on roads/);
  assert.match(folded, new RegExp(`<details class="fold zoom-notes"><summary>${ZOOM_LEVELS_LINK}</summary>`));
  assert.ok(folded.indexOf("<details") < folded.indexOf("The map is at zoom 11."), "the long text is inside the disclosure");
  assert.ok(folded.includes(CAR_FREE_NOTE));
  // Unfolded, as before: no disclosure.
  assert.doesNotMatch(renderToStaticMarkup(createElement(StressZoomNotes, { zoom: 11, shown: true })), /<details/);
});

// ---- the font and the stylesheet ------------------------------------------------

test("Atkinson Hyperlegible is self-hosted from /fonts/, with the old system stack as the fallback", () => {
  const faces = [...css.matchAll(/@font-face \{([^}]*)\}/g)].map((m) => m[1]);
  assert.equal(faces.length, 2);
  const urls = faces.flatMap((face) => [...face.matchAll(/url\("([^"]+)"\)/g)].map((m) => m[1]));
  assert.deepEqual(urls.sort(), ["/fonts/atkinson-hyperlegible-bold.woff2", "/fonts/atkinson-hyperlegible-regular.woff2"]);
  for (const face of faces) assert.match(face, /font-display: swap/);
  assert.match(css, /--font: "Atkinson Hyperlegible", system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif;/);
  assert.match(css, /font-family: var\(--font\);/);
  // font-src 'self': no font service, no external URL anywhere in the stylesheet or the page.
  assert.doesNotMatch(css, /fonts\.googleapis|fonts\.gstatic|https?:\/\/[^"')]*\.(woff2?|ttf|otf)/);
  assert.doesNotMatch(src("../../index.html"), /googleapis|gstatic|<link[^>]*font/i);
});

test("the sidebar's own buttons and summaries are 44 px high at least", () => {
  assert.match(css, /\.panel button,\s*\.panel summary \{\s*min-height: 44px;/);
  assert.match(css, /\.panel \.bar-button \{[^}]*min-height: 56px/);
  assert.match(css, /\.ride-line-button \{[^}]*min-height: 56px/);
  assert.match(css, /\.sheet-back \{[^}]*min-width: 44px/);
});

test("the beta banner is still the first child of the panel's body, before the scrolling part", () => {
  const body = app.indexOf('<div id="panel-body"');
  const open = app.indexOf(">", body) + 1;
  assert.match(app.slice(open, app.indexOf("<BetaBanner")), /^\s*$/);
  assert.ok(app.indexOf("<BetaBanner") < app.indexOf('className="panel-scroll"'));
});

test("the skip link and its target stay: #route-planner is the aside, and every live region is still in the page", () => {
  assert.match(app, /href="#route-planner"/);
  assert.match(app, /id="route-planner"\s+tabIndex=\{-1\}/);
  assert.match(app, /<div role="status" aria-live="polite" className="status-line">/);
  assert.match(app, /\{said\.text\}/);
  assert.match(app, /announce\(addedSaid\(next\.indexOf\(point\), next\.length, loopVias\)\)/);
});

test("on a desktop the points come first, then the Ride line, then the route; on a phone the route leads", () => {
  assert.deepEqual(sheetOrder(false, "idle", false), ["points", "presets", "route"]);
  assert.deepEqual(sheetOrder(false, "ok", true), ["points", "presets", "route"]);
  assert.deepEqual(sheetOrder(true, "ok", true), ["route", "points", "presets"]);
  assert.deepEqual(sheetOrder(true, "idle", false), ["points", "presets", "route"]);
});

test("with a route shown the points are compact, behind 'Edit points', and the controls stay in the page", () => {
  assert.match(app, /const compactPoints = routeShownForPoints && points\.length >= 2 && !editPoints;/);
  assert.match(app, /<div className="points-controls" hidden=\{compactPoints\}>\s*<PlaceSearch/);
  assert.match(app, /aria-expanded=\{!compactPoints\}\s+aria-controls="points-edit"/);
  assert.match(app, /<div id="points-edit" hidden=\{compactPoints\}>/);
});
