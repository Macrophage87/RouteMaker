// The sidebar redesign (OWNER-DECISIONS 312, mockup v3): the Ride line's words, the quick figures,
// the bottom bar, the folds and the font. App.tsx and the .tsx components are not rendered by a test
// (no DOM here, and node reads no JSX), so where they place things is read as source, as the other
// panels' wiring is; the decisions they make (the focus, the copied link, the breakdown's split) are
// pure functions, tested here, and the parts in lib/sidebarParts.ts are rendered.
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { startDials, type Dials } from "./dials.ts";
import { hillsShort, rideSummary, rideSummarySpoken, targetShort, trafficShort, whenShort } from "./rideSummary.ts";
import { NOT_AVAILABLE, calmPercent, heavyMetres, junctionFigure, quickFigures, stressBarKey, stressBarLabel } from "./quickFigures.ts";
import {
  BACK_LABEL,
  BAR_ITEMS,
  BAR_NAME,
  barCurrent,
  COPY_LINK,
  COPY_LINK_DONE,
  COPY_LINK_FAILED,
  MASS_RIDE_LAYERS_NOTE,
  MORE_TIPS,
  FEWER_TIPS,
  PLANNER_EXTRAS,
  PLANNER_TITLE,
  RIDE_ACTION_SPOKEN,
  ROUTE_FOLDS,
  SHEET_TITLES,
  copyText,
  focusOnViewChange,
  foldTitle,
  linkSaidFor,
  linkToCopy,
  noticeSaidElsewhere,
  rescueCompactFocus,
  rideActionLabel,
  searchLede,
  sheetEscape,
  stepsCount,
  type BarItem,
  type PanelView,
  type SheetKeyEvent,
  type ViewCause,
} from "./sidebar.ts";
import { encodePlan } from "./planHash.ts";
import { WEIGHT_STORAGE_KEY } from "./weight.ts";
import { stressSegments } from "./stressBar.ts";
import { StressZoomNotes, ZOOM_LEVELS_LINK, CAR_FREE_NOTE, stressZoomNotice } from "./stressLegend.ts";
import { sheetOrder } from "./sheet.ts";
import { FederalPointsList } from "./federalLegend.ts";
import { ACCESSIBILITY_ADDRESS_NOTE, ACCESSIBILITY_CLASS, ACCESSIBILITY_CONTRAST_NOTE, ACCESSIBILITY_HINT, ACCESSIBILITY_LABEL, AccessibilitySwitch } from "./accessibilitySwitch.ts";
import { ACCESSIBILITY_STORAGE_KEY } from "../stressStyle.js";
import { breakdownParts } from "./facilityBar.ts";
// The rendered parts are createElement modules: node's test runner reads .ts, not .tsx.
import { HighContrastShortcut, Fold, JunctionLegend, PlannerZoomNotice, RideSettings } from "./sidebarParts.ts";

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
  // The words change where stressWords and hillsWords change (mutation NIT 1: each edge, both sides).
  const traffic: Array<[number, string]> = [
    [10, "traffic tolerant"], [11, "direct"], [29, "direct"], [30, "balanced traffic"], [50, "balanced traffic"],
    [51, "quiet streets"], [74, "quiet streets"], [75, "low stress"], [80, "low stress"], [81, "calm"], [94, "calm"], [95, "calmest"],
  ];
  for (const [stress, words] of traffic) assert.equal(trafficShort(stress), words, `traffic ${stress}`);
  const hills: Array<[number, string]> = [
    [-80, "avoids hills"], [-79, "gentler hills"], [-11, "gentler hills"], [-10, "balanced hills"], [10, "balanced hills"],
    [11, "some climbing"], [79, "some climbing"], [80, "seeks hills"],
  ];
  for (const [value, words] of hills) assert.equal(hillsShort(value), words, `hills ${value}`);
  assert.match(rideSummary("default", { ...startDials("default"), assist: true }), /^Default, electric assist · /);
  assert.match(rideSummary("mass-ride", startDials("mass-ride")), /^Mass Ride · most direct roadway · avoids hills · now$/);
  // A loop set on a Mass Ride is hidden there (374): the summary does not say it.
  assert.doesNotMatch(rideSummary("mass-ride", { ...startDials("mass-ride"), loop: true }), /loop/);
  // Cargo says its load.
  assert.match(rideSummary("cargo", startDials("cargo", "people")), /^Cargo Bike, cargo with passengers · /);
});

test("the Ride line says a set target distance, miles first, after when (312's order)", () => {
  assert.equal(targetShort(undefined), null);
  assert.equal(targetShort(32187), "about 20.0 mi (32.2 km)");
  const dials: Dials = { ...startDials("default"), targetDistanceM: 32187, loop: true };
  assert.equal(rideSummary("default", dials), "Default · quiet streets · balanced hills · now · about 20.0 mi (32.2 km) · loop");
  assert.equal(rideSummarySpoken("default", dials), "Default, quiet streets, balanced hills, now, about 20.0 mi (32.2 km), loop");
});

test("the Ride line never carries the rider and bike weight (313-314): not a figure, not the dial", () => {
  const withWeight: Dials = { ...startDials("default"), systemWeightKg: 123 };
  assert.equal(rideSummary("default", withWeight), rideSummary("default", startDials("default")));
  assert.doesNotMatch(rideSummary("default", withWeight), /123|lb|kg|weight/i);
  assert.doesNotMatch(src("./rideSummary.ts").replace(/\/\*[\s\S]*?\*\//g, ""), /systemWeight|weight/i);
});

test("the Ride line is a heading holding a button with aria-expanded, whose words are read with commas", () => {
  const html = renderToStaticMarkup(
    createElement(RideSettings, { summary: "Default · now", spoken: "Default, now", children: createElement("p", null, "controls") }),
  );
  // The region is named "Ride" alone, not by the whole button (the a11y review's N4).
  assert.match(
    html,
    /^<section class="ride-settings" aria-label="Ride"><h2 id="ride-settings-heading" class="ride-line"><button type="button" class="ride-line-button" aria-expanded="false" aria-controls="[^"]+">/,
  );
  assert.match(html, /<span class="ride-line-summary" aria-hidden="true">Default · now<\/span><span class="visually-hidden">: Default, now\.<\/span>/);
  // Shown Edit or Done, heard Edit whatever the state: aria-expanded says it (no "Done, expanded": N8).
  assert.match(html, /<span class="ride-line-action" aria-hidden="true">Edit<\/span><span class="visually-hidden"> Edit<\/span>/);
  assert.equal(rideActionLabel(false), "Edit");
  assert.equal(rideActionLabel(true), "Done");
  assert.equal(RIDE_ACTION_SPOKEN, "Edit");
  // The controls stay in the page while closed, so nothing they hold is lost.
  assert.match(html, /<div id="[^"]+" class="ride-settings-body" hidden=""><p>controls<\/p><\/div>/);
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
    "Avoid gravel",
  ].map(at);
  assert.deepEqual(order, [...order].sort((a, b) => a - b), "Traffic, Hills, When, target distance, weight, gravel");
  // "Make it a loop" is no longer behind the Edit button (OWNER-DECISIONS 388): it is by the search, in the Points section.
  assert.doesNotMatch(dials, /loopView|withLoop|type="checkbox"\s+checked=\{loop/, "the dials panel has no loop toggle");
  const points = app.slice(app.indexOf("const pointsSection ="), app.indexOf("const routeSection ="));
  const inPoints = (text: string) => {
    const i = points.indexOf(text);
    assert.ok(i > 0, text);
    return i;
  };
  assert.deepEqual(
    ["<PlaceSearch", "{loop && (", "{searchLede(loopVias)}", "Add point at map center"].map(inPoints),
    ["<PlaceSearch", "{loop && (", "{searchLede(loopVias)}", "Add point at map center"].map(inPoints).sort((a, b) => a - b),
    "the search, then the loop box, then the points and Add point at map center",
  );
  assert.ok(inPoints("{loop && (") > points.indexOf("</div>", inPoints('id="points-search"')), "outside the part that hides while the points compact");
  assert.match(points, /aria-describedby=\{loopHintId\}/);
  assert.match(app, /const loopHintId = useId\(\);/, "a generated id, not a fixed one");
  // The hint is plain visible text: a paragraph with the id the box points at, and no live region or hidden class on it.
  assert.match(points, /<p className="hint" id=\{loopHintId\}>\s*\{loop\.hint\}\s*<\/p>/);
  assert.match(points, /commitDials\(withLoop\(dials, event\.target\.checked\)\)/, "its change goes through the announcing commit");
  assert.match(app, /const loop = loopView\(preset, dials\.loop, points\);/);
  // The weight row is the existing one: status only, Change opening the private dialog (weightDialog.ts).
  assert.match(dials, /import \{ WeightSetting \} from "\.\/lib\/weightDialog\.ts";/);
});

// ---- points first ------------------------------------------------------------

test("the points come first, the how-to is behind More tips, and Reverse, Undo and Clear share a row", () => {
  assert.equal(MORE_TIPS, "More tips");
  assert.equal(FEWER_TIPS, "Fewer tips");
  // The keyboard's way in stays in view (the a11y review's S6).
  assert.equal(searchLede(false), "Search, click the map, or use Add point at map center: start, then end. Later clicks add stops.");
  assert.equal(searchLede(true), "Search, click the map, or use Add point at map center: start, then stops. The ride comes back to the start.");
  // The start-up how-to only before any point; with points, how to change them (the correctness review's N5).
  assert.match(
    app,
    /<MoreTips>[\s\S]{0,200}\{points\.length > 0 \? <p className="hint">\{editingTips\(\)\}<\/p> : <p className="hint">\{emptyPlanHint\(preset, loopVias\)\}<\/p>\}/,
  );
  assert.match(sidebar, /aria-expanded=\{open\} aria-controls=\{id\}/);
  // Add point at map center first, then the compact row; every existing button is still there.
  const labels = ["Add point at map center", "Reverse", "Undo", "Redo", "Clear"].map((t) => app.indexOf(t, app.indexOf('className="actions point-add"')));
  assert.ok(labels.every((i) => i > 0));
  assert.deepEqual(labels, [...labels].sort((a, b) => a - b));
  assert.match(app, /ref=\{addRef\}/);
  assert.match(app, /aria-describedby=\{reverseHint \? "reverse-hint" : undefined\}/);
  assert.match(app, /<p className="hint" id="reverse-hint">/);
});

test("with a route shown the points are compact, behind 'Edit points', and the controls stay in the page", () => {
  assert.match(app, /const compactPoints = routeShownForPoints && points\.length >= 2 && !editPoints;/);
  assert.match(app, /<div id="points-search" ref=\{pointsSearchRef\} className="points-controls" hidden=\{compactPoints\}>\s*<PlaceSearch/);
  // Edit points controls both parts it hides (the correctness review's N6).
  assert.match(app, /aria-expanded=\{!compactPoints\}\s+aria-controls="points-search points-edit"/);
  assert.match(app, /<div id="points-edit" ref=\{pointsEditRef\} hidden=\{compactPoints\}>/);
  // Clear, a plan from a link, or fewer than two points: the next route opens compact again (N1).
  assert.match(app, /const clearAll = \(\) => \{\s*setConfirmedKm\(null\);\s*setEditPoints\(false\);/);
  assert.match(app, /setEditPoints\(false\);\s*setPoints\(plan\.points\);/);
  assert.match(app, /setStatus\(\{ kind: "idle" \}\);\s*\/\/ The next route opens compact again[^\n]*\n\s*setEditPoints\(false\);/);
});

test("the points compacting never leaves the focus in a hidden part: it goes to Edit points (the review's B1)", () => {
  // A stand-in for the page: the two parts that hide, what had the focus, and Edit points.
  const part = () => {
    const kids = new Set<unknown>();
    return { kids, contains: (node: unknown) => kids.has(node) };
  };
  const make = () => {
    const search = part();
    const tools = part();
    const combobox = { name: "combobox" };
    const addButton = { name: "add" };
    const removeButton = { name: "remove" };
    search.kids.add(combobox);
    tools.kids.add(addButton);
    let focused: unknown = null;
    const editPoints = {
      focus() {
        focused = editPoints;
      },
    };
    return { search, tools, combobox, addButton, removeButton, editPoints, focused: () => focused };
  };
  type Before = "combobox" | "addButton" | "removeButton" | null;
  const cases: Array<{ name: string; before: Before; wasCompact: boolean; compact: boolean; moves: boolean }> = [
    { name: "a route arrives with the focus in the search", before: "combobox", wasCompact: false, compact: true, moves: true },
    { name: "a route arrives with the focus on Add point at map center", before: "addButton", wasCompact: false, compact: true, moves: true },
    { name: "a route arrives with the focus on a point's Remove (still shown)", before: "removeButton", wasCompact: false, compact: true, moves: false },
    { name: "a route arrives with the focus on the page", before: null, wasCompact: false, compact: true, moves: false },
    { name: "already compact", before: "combobox", wasCompact: true, compact: true, moves: false },
    { name: "opening the points again", before: "addButton", wasCompact: true, compact: false, moves: false },
    { name: "no route", before: "addButton", wasCompact: false, compact: false, moves: false },
  ];
  for (const c of cases) {
    const page = make();
    const before = c.before === null ? null : page[c.before];
    const moved = rescueCompactFocus({ wasCompact: c.wasCompact, compact: c.compact, before, hidden: [page.search, page.tools], editPoints: page.editPoints });
    assert.equal(moved, c.moves, c.name);
    assert.equal(page.focused(), c.moves ? page.editPoints : null, c.name);
  }
  // No Edit points button, or the parts not in the page yet: nothing to do, and no error.
  const page = make();
  assert.equal(rescueCompactFocus({ wasCompact: false, compact: true, before: page.combobox, hidden: [null, null], editPoints: page.editPoints }), false);
  assert.equal(rescueCompactFocus({ wasCompact: false, compact: true, before: page.combobox, hidden: [page.search], editPoints: null }), false);
  // App runs it in a layout effect on compactPoints, with what had the focus before that render.
  assert.match(
    app,
    /useLayoutEffect\(\(\) => \{\s*rescueCompactFocus\(\{\s*wasCompact: wasCompact\.current,\s*compact: compactPoints,\s*before: focusBeforeRender\.current,\s*hidden: \[pointsSearchRef\.current, pointsEditRef\.current\],\s*editPoints: editPointsRef\.current,\s*\}\);\s*wasCompact\.current = compactPoints;\s*\}, \[compactPoints\]\);/,
  );
  assert.match(app, /ref=\{editPointsRef\}\s+className="secondary edit-points"/);
  // After the sheet-order effect, which may first put the focus back on the (now hidden) element.
  assert.ok(app.indexOf("rescueCompactFocus({") > app.indexOf("}, [routeFirst]);"));
});

test("the points notice is said through the app's region while the planner is hidden, and only then (recheck S1)", () => {
  assert.equal(noticeSaidElsewhere("That point is outside the area this map covers.", false), true);
  assert.equal(noticeSaidElsewhere("That point is outside the area this map covers.", true), false, "the planner's own status says it");
  assert.equal(noticeSaidElsewhere(null, false), false);
  assert.equal(noticeSaidElsewhere("", false), false);
  assert.match(app, /plannerShownNow\.current = view === "planner" && panelOpen;/);
  assert.match(app, /if \(noticeSaidElsewhere\(notice, plannerShownNow\.current\)\) announce\(notice as string\);\s*\}, \[notice, announce\]\);/);
});

test("a Mass Ride loads the federal-land data whatever the shading switch says, for the planner's list (recheck R-N1)", () => {
  assert.match(app, /federalWanted=\{federalShown\(preset, true\)/);
  const map = src("../MapView.tsx");
  assert.match(map, /if \(!\(visible \|\| callbacks\.current\.federalWanted\) \|\| federalLoading\) return;/);
  assert.match(map, /\}, \[props\.federalVisible, props\.federalWanted\]\);/);
});

test("Mass Ride's points on federal land are listed in the planner too, with their own heading id", () => {
  const points = app.slice(app.indexOf("const federalPlanner"), app.indexOf("const routeSection"));
  assert.match(points, /federalShown\(preset, true\) && \(/);
  assert.match(points, /<FederalPointsList[\s\S]*headingId="federal-points-planner-heading"/);
  assert.match(points, /\{federalPlanner\}/);
  const html = renderToStaticMarkup(
    createElement(FederalPointsList, {
      found: [{ index: 0, name: "National Mall", manager: "NPS" }] as never,
      count: 2,
      nameOf: () => "Start",
      headingId: "x-heading",
    }),
  );
  assert.match(html, /<p id="x-heading">[^<]+<\/p><ul aria-labelledby="x-heading"><li>Start – National Mall \(NPS\)<\/li><\/ul>/);
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

test("the paths-and-quiet-streets figure is always the bar key's LTS 1 plus LTS 2 (the correctness review's N3)", () => {
  // Rounded on their own, the sum and the two shares in the key could differ by one.
  for (const stress of [{ "1": 6060, "2": 3040, "3": 900 }, { "1": 6049, "2": 3049, "3": 902 }, { "1": 333, "2": 333, "3": 334 }]) {
    const keyed = stressSegments(stress);
    const sum = keyed.filter((s) => s.key === "1" || s.key === "2").reduce((n, s) => n + s.percent, 0);
    assert.equal(calmPercent(stress), sum, JSON.stringify(stress));
  }
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
    { short: "LTS 1", label: "Comfortable for most people", percent: 61 },
    { short: "LTS 2", label: "Comfortable for most adults", percent: 30 },
    { short: "LTS 3", label: "For confident riders", percent: 0 },
    { short: "LTS 4", label: "Heavy or fast traffic", percent: 9 },
  ];
  // The tier, what it means, then its share, so "LTS 1" and "61" are never heard as one number; and no
  // "Traffic stress along the route" again, which the figure's caption already names (the a11y review's S2).
  assert.equal(
    stressBarLabel(segments),
    "LTS 1, comfortable for most people: 61 percent; LTS 2, comfortable for most adults: 30 percent; LTS 4, heavy or fast traffic: 9 percent",
  );
  assert.equal(stressBarKey(segments), "LTS 1: 61%, LTS 2: 30%, LTS 4: 9%");
  // Avoid is not read "Avoid, legal, but best avoided" (recheck N-new-1).
  assert.equal(stressBarLabel([{ key: "5", short: "Avoid", label: "Legal, but best avoided", percent: 2 }]), "Avoid, roads best avoided: 2 percent");
  assert.match(app, /<figure className="stress stress-main" aria-labelledby="stress-figure-caption">/);
  assert.match(app, /<div className="stress-bar" role="img" aria-label=\{stressBarLabel\(segments\)\}>/);
  assert.match(app, /<p className="stress-key" aria-hidden="true">/);
});

test("the route's folds: Stress and facilities, Directions, Junctions to watch, Routes to choose from; no elevation chart yet", () => {
  assert.equal(foldTitle("Junctions to watch", 4), "Junctions to watch (4)");
  assert.equal(foldTitle("Stress and facilities", null), "Stress and facilities");
  assert.equal(stepsCount(1), "1 step");
  assert.equal(stepsCount(12), "12 steps");
  // The edges (the mutation re-check's NIT B): a count of 0 is still said, as "(0)" and "0 steps".
  assert.equal(foldTitle("x", 0), "x (0)");
  assert.equal(stepsCount(0), "0 steps");
  // The Junctions fold: drawn only when the route has intersections, and counted by what the list shows.
  assert.match(app, /const junctions = route\.intersections == null \? null : junctionItems\(route\)\.length;/);
  assert.match(app, /\{junctions !== null && \(\s*<Fold title=\{foldTitle\(ROUTE_FOLDS\.junctions\.title, junctions\)\}/);
  const at = (text: string) => {
    const i = app.indexOf(text, app.indexOf("function RouteSummary"));
    assert.ok(i > 0, text);
    return i;
  };
  const order = [
    "<Fold title={ROUTE_FOLDS.facilities.title}",
    "<RouteDescription route={route} fold />",
    "foldTitle(ROUTE_FOLDS.junctions.title, junctions)",
    "foldTitle(ROUTE_FOLDS.choices.title, pickerCount)",
  ].map(at);
  assert.deepEqual(order, [...order].sort((a, b) => a - b));
  assert.doesNotMatch(app, /Elevation and stress/, "the elevation chart is not in the app (322), so there is no section for it");
  // Each fold is reached from a heading list: a hidden h3 before it (the a11y review's S5).
  for (const key of ["facilities", "junctions", "choices"] as const) {
    assert.ok(app.includes(`heading={ROUTE_FOLDS.${key}.title} open={ROUTE_FOLDS.${key}.open}`), key);
  }
  assert.match(app, /<h3 className="visually-hidden">Totals<\/h3>\s*<dl className="stats totals">/);
  // The notices stay in view; only the figures are folded.
  assert.match(app, /<FacilityBreakdown route=\{route\} part="notices" \/>/);
  assert.match(app, /<FacilityBreakdown route=\{route\} part="figures" \/>/);
});

test("a Fold: closed unless open, 'Routes to choose from' open by default, and its hidden h3 first", () => {
  assert.deepEqual(Object.fromEntries(Object.entries(ROUTE_FOLDS).map(([k, v]) => [k, v.open])), {
    facilities: false,
    directions: false,
    junctions: false,
    choices: true,
  });
  const closed = renderToStaticMarkup(createElement(Fold, { title: "Junctions to watch (4)", heading: "Junctions to watch", children: "x" }));
  assert.equal(
    closed,
    '<h3 class="visually-hidden">Junctions to watch</h3><details class="fold"><summary>Junctions to watch (4)</summary><div class="fold-body">x</div></details>',
  );
  const open = renderToStaticMarkup(createElement(Fold, { title: "Routes to choose from (3)", open: ROUTE_FOLDS.choices.open, children: "x" }));
  assert.match(open, /^<details class="fold" open="">/);
});

test("FacilityBreakdown's parts: the notices only in 'notices', the figures only in 'figures', both in 'all' (mutation SF3)", () => {
  assert.deepEqual(breakdownParts("notices"), { notices: true, figures: false });
  assert.deepEqual(breakdownParts("figures"), { notices: false, figures: true });
  assert.deepEqual(breakdownParts("all"), { notices: true, figures: true });
  // Every block of the component is gated by the flag for its half: two figures, three notices.
  const breakdown = src("../FacilityBreakdown.tsx");
  assert.match(breakdown, /const \{ figures, notices \} = breakdownParts\(part\);/);
  const gates = [...breakdown.matchAll(/\{(figures|notices) && ([^&]+?) && \(\s*<(figure|p) className="([^"]+)"/g)].map((m) => `${m[1]}:${m[4]}`);
  assert.deepEqual(gates, [
    "figures:stress route-colours",
    "notices:notice traffic-tolerant",
    "notices:notice avoid",
    "figures:stress facility",
    "notices:hint seek",
  ]);
});

test("Directions as a fold: an h3 first, a closed details named with its steps, no fold for no steps (mutation SF3)", () => {
  const html = renderToStaticMarkup(
    createElement(Fold, {
      title: foldTitle(ROUTE_FOLDS.directions.title, stepsCount(2)),
      heading: ROUTE_FOLDS.directions.title,
      headingId: "route-description-heading",
      open: false,
      className: "route-description",
      children: createElement("ol", { className: "description-list" }),
    }),
  );
  assert.equal(
    html,
    '<h3 id="route-description-heading" class="visually-hidden">Directions</h3><details class="fold route-description"><summary>Directions (2 steps)</summary><div class="fold-body"><ol class="description-list"></ol></div></details>',
  );
  const component = src("../RouteDescription.tsx");
  const fold = component.slice(component.indexOf("if (fold) {"), component.indexOf('<section className="route-description"'));
  assert.match(fold, /if \(entries\.length === 0\) return null;/, "no \"Directions (0 steps)\"");
  assert.match(fold, /<Fold\s+title=\{foldTitle\(ROUTE_FOLDS\.directions\.title, stepsCount\(entries\.length\)\)\}\s+heading=\{ROUTE_FOLDS\.directions\.title\}\s+headingId="route-description-heading"\s+open=\{open\}/);
  // The rider's open or closed is remembered (writeOpen), once per change.
  assert.match(fold, /onToggle=\{\(now\) => \{\s*if \(now !== open\) \{\s*setOpen\(now\);\s*writeOpen\(now\);/);
  assert.match(fold, /<ol className="description-list">\{items\}<\/ol>/);
});

test("GPX and Copy link are pinned under the scrolling part, outside it", () => {
  assert.equal(COPY_LINK, "Copy link");
  const scrollEnd = app.indexOf("</div>\n\n          {/* Pinned under");
  const pinned = app.indexOf('<div className="route-actions">');
  assert.ok(scrollEnd > 0 && pinned > scrollEnd, "outside .panel-scroll");
  assert.match(app, /onClick=\{\(\) => downloadGpx\(shown, routedPoints, routedLoop\)\}>\s*Download GPX/);
  assert.match(app, /<span role="status" className="visually-hidden">\s*\{linkSaid\}/);
  // Unpinned while a sheet is open (the mutation re-check's NIT D): only the planner view shows the actions.
  assert.match(app, /\{view === "planner" && shown && \(\s*<div className="route-actions">/);
  // The link is this page and encodePlan's fragment, which never carries the weight (313).
  assert.match(app, /copyText\(linkToCopy\(window\.location, points, preset, dials\), navigator\.clipboard, selectionCopy\)/);
  assert.equal(linkSaidFor(true), COPY_LINK_DONE);
  assert.equal(linkSaidFor(false), COPY_LINK_FAILED);
  assert.match(app, /if \(press === linkPresses\.current\) setLinkSaid\(linkSaidFor\(done\)\);/);
  // Cleared first, so a second press is said again.
  assert.match(app, /const press = \+\+linkPresses\.current;\s*setLinkSaid\(""\);/);
});

test("App writes exactly encodePlan's fragment to the address bar, and a new plan clears 'Link copied.'", () => {
  const writer = app.slice(app.indexOf("// Keep the link in step with the plan"), app.indexOf("}, [points, preset, dials]);"));
  assert.match(writer, /const hash = encodePlan\(points, preset, dials\);\s*writtenHash\.current = hash;\s*window\.history\.replaceState\(null, "", hash\);/);
  assert.equal((writer.match(/replaceState/g) ?? []).length, 1);
  assert.match(writer, /linkPresses\.current \+= 1;\s*setLinkSaid\(""\);/);
  // planDials (the dials with the weight) never reaches the address bar.
  assert.doesNotMatch(writer.replace(/\/\/[^\n]*/g, ""), /planDials|weight/i);
});

test("the copied link is encodePlan's, and never holds the weight, even with one stored and one in the dials", () => {
  const was = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  const stored = new Map([[WEIGHT_STORAGE_KEY, JSON.stringify({ kg: 97.5, at: 1 })]]);
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: { getItem: (k: string) => stored.get(k) ?? null, setItem: () => {}, removeItem: () => {} },
  });
  try {
    const points: Array<[number, number]> = [
      [-77.03, 38.9],
      [-77.05, 38.92],
    ];
    const dials: Dials = { ...startDials("default"), systemWeightKg: 123 };
    const where = { origin: "https://x.test", pathname: "/", search: "?palette=cool" };
    const link = linkToCopy(where, points, "default", dials);
    assert.equal(link, `https://x.test/?palette=cool${encodePlan(points, "default", dials)}`);
    assert.doesNotMatch(link, /weight|sysweight|97|123|kg|lb/i);
  } finally {
    if (was) Object.defineProperty(globalThis, "localStorage", was);
    else delete (globalThis as { localStorage?: unknown }).localStorage;
  }
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

test("the bottom bar is Plan, Map layers, Legend, GPX and Settings: real buttons, each with words", () => {
  assert.deepEqual(BAR_ITEMS.map((i) => i.label), ["Plan", "Map layers", "Legend", "GPX", "Settings"]);
  assert.deepEqual(BAR_ITEMS.map((i) => i.opens), ["planner", "layers", "layers", "gpx", "settings"]);
  assert.equal(BAR_ITEMS[0].id, "plan", "Plan is first (OWNER-DECISIONS 392, 393)");
  assert.equal(BAR_ITEMS.filter((i) => i.toLegend).length, 1, "only Legend opens at the legend");
  assert.ok(BAR_ITEMS.every((i) => i.description.length > 0));
  assert.equal(BAR_ITEMS[4].description, "Opens the settings: display options and signing in.");
  assert.equal(BAR_NAME, "Panel pages", "a landmark name that says what the bar is (the a11y review's N3)");
  assert.match(sidebar, /<nav aria-label=\{BAR_NAME\} className="bottom-bar">/);
  assert.match(sidebar, /<Fragment key=\{item\.id\}>\s*<button\s+id=\{`bar-\$\{item\.id\}`\}\s+type="button"/);
  // The hint is a sibling of the button, not inside it: the name is the label alone, the hint the description once.
  assert.match(sidebar, /<\/button>\s*\{\/\*[\s\S]*?\*\/\}\s*<span id=\{`bar-\$\{item\.id\}-hint`\} hidden>\s*\{item\.description\}\s*<\/span>\s*<\/Fragment>/);
  assert.match(sidebar, /aria-describedby=\{`bar-\$\{item\.id\}-hint`\}/);
  assert.equal(BAR_ITEMS[0].description, "Shows the planner: the points, the ride settings and the route.");
  assert.match(sidebar, /<span>\{item\.label\}<\/span>/);
  assert.match(sidebar, /<svg[^>]*aria-hidden="true">\s*\{ICONS\[item\.id\]\}/);
  assert.doesNotMatch(sidebar, /<a /, "no link where a button is meant");
});

test("a sheet: Back is a labelled button, its heading takes the focus, Escape goes back", () => {
  assert.deepEqual(Object.values(SHEET_TITLES), ["Map layers", "GPX file", "Settings"]);
  // In visible words, not only an arrow, so the name and the label are one (OWNER-DECISIONS 393).
  assert.equal(BACK_LABEL, "Back to planner");
  assert.doesNotMatch(sidebar, /aria-label="Back to the planner"/);
  assert.match(sidebar, /<button type="button" className="sheet-back" onClick=\{onBack\}>[\s\S]*?<\/svg>\s*\{BACK_LABEL\}\s*<\/button>/, "Back goes back (NIT A)");
  assert.match(sidebar, /<h2 id=\{`\$\{id\}-title`\} ref=\{headingRef\} tabIndex=\{-1\}>/);
  assert.match(
    sidebar,
    /sheetEscape\(\{ key: event\.key, defaultPrevented: event\.defaultPrevented, target: event\.target as HTMLElement, preventDefault: \(\) => event\.preventDefault\(\) \}, onBack\)/,
  );
  // The legend's heading and the error can take the focus (focus() on an element without tabIndex does nothing).
  assert.match(app, /<h3 id="legend-heading" ref=\{legendHeadingRef\} tabIndex=\{-1\}>/);
  assert.match(app, /<div ref=\{errorRef\} tabIndex=\{-1\} className=\{`error error-\$\{status\.error\.kind\}`\} role="alert">/);
});

test("where the focus goes on every change of view (mutation SF1)", () => {
  const views: PanelView[] = ["planner", "layers", "gpx", "settings"];
  const causes: ViewCause[] = ["bar", "back", "error", "confirm", "planButton", "panelToggle"];
  const ids: BarItem["id"][] = ["layers", "legend", "gpx", "settings"];
  for (const was of views)
    for (const view of views)
      for (const legendTarget of [false, true])
        for (const openedBy of ids)
          for (const cause of causes) {
            const got = focusOnViewChange({ was, view, legendTarget, openedBy, cause });
            const at = `${was}->${view} legend=${legendTarget} by=${openedBy} ${cause}`;
            if (was === view) assert.equal(got, null, at);
            else if (view !== "planner") assert.deepEqual(got, { kind: "heading", view, legend: view === "layers" && legendTarget }, at);
            else if (cause === "error") assert.deepEqual(got, { kind: "error" }, at);
            else if (cause === "confirm") assert.deepEqual(got, { kind: "plan" }, at);
            else if (cause === "planButton") assert.deepEqual(got, { kind: "planner" }, at);
            else if (cause === "panelToggle") assert.equal(got, null, at);
            else assert.deepEqual(got, { kind: "bar", id: openedBy }, at);
          }
  // The cases a rider meets, spelled out.
  const go = (was: PanelView, view: PanelView, legendTarget: boolean, openedBy: BarItem["id"], cause: ViewCause) =>
    focusOnViewChange({ was, view, legendTarget, openedBy, cause });
  assert.deepEqual(go("planner", "layers", true, "legend", "bar"), { kind: "heading", view: "layers", legend: true });
  assert.deepEqual(go("planner", "layers", false, "layers", "bar"), { kind: "heading", view: "layers", legend: false });
  assert.deepEqual(go("planner", "gpx", true, "gpx", "bar"), { kind: "heading", view: "gpx", legend: false }, "only the layers sheet has a legend");
  assert.deepEqual(go("gpx", "planner", false, "gpx", "back"), { kind: "bar", id: "gpx" });
  assert.deepEqual(go("layers", "planner", true, "legend", "back"), { kind: "bar", id: "legend" });
  assert.deepEqual(go("gpx", "planner", false, "gpx", "error"), { kind: "error" });
  assert.deepEqual(go("layers", "planner", false, "layers", "confirm"), { kind: "plan" });
  // The Plan button (OWNER-DECISIONS 392): the planner's heading, from any sheet; nothing from the pure decision when it is already showing (App handles that case).
  for (const sheet of ["layers", "gpx", "settings"] as const) assert.deepEqual(go(sheet, "planner", false, sheet, "planButton"), { kind: "planner" });
  assert.equal(go("planner", "planner", false, "layers", "planButton"), null);
  assert.match(app, /if \(item\.opens === "planner"\) \{\s*showPlanner\(\);\s*return;/);
  // From a sheet the view changes and the focus decision does it; on the planner already, the heading is focused and the panel scrolled to the top.
  assert.match(app, /const showPlanner = \(focusHeading = true\) => \{\s*viewCause\.current = focusHeading \? "planButton" : "panelToggle";[\s\S]*?if \(viewNow\.current === "planner"\) \{\s*if \(focusHeading\) \{\s*plannerHeadingRef\.current\?\.focus\(\);\s*panelBodyRef\.current\?\.scrollTo\?\.\(\{ top: 0 \}\);\s*\}\s*\} else setView\("planner"\);/);
  // The phone header's toggle: "Show planner" always shows the planner, even if a sheet was open when it was hidden,
  // and leaves the focus on the toggle (showPlanner(false)); the heading focus is the Plan button's.
  assert.match(app, /\{panelOpen \? "Hide planner" : "Show planner"\}/);
  assert.match(app, /if \(panelOpen\) setPanelOpen\(false\);\s*else \{\s*setPanelOpen\(true\);[\s\S]*?showPlanner\(false\);/);
  assert.match(app, /target\.kind === "planner"\) \{[^}]*plannerHeadingRef\.current\?\.focus\(\);/);
  assert.match(app, /<h1 ref=\{plannerHeadingRef\} tabIndex=\{-1\}>\s*\{PLANNER_TITLE\}\s*<\/h1>/);
  assert.equal(PLANNER_TITLE, "RouteMaker");  // App records why: a bar button, Back, or the status that brought the planner back.
  assert.match(app, /openedBy\.current = item\.id;\s*viewCause\.current = "bar";/);
  assert.match(app, /viewCause\.current = "back";\s*setView\("planner"\);/);
  assert.match(app, /viewCause\.current = status\.kind === "confirm" \? "confirm" : "error";\s*setView\("planner"\);/);
  assert.match(app, /focusOnViewChange\(\{ was, view, legendTarget, openedBy: openedBy\.current, cause: viewCause\.current \}\)/);
  assert.match(app, /prevView\.current = view;/);
  // The long-ride question takes the focus when it comes, not again on the way back from a sheet (N8).
  assert.match(app, /if \(focusPlan && viewNow\.current === "planner"\) planButtonRef\.current\?\.focus\(\);\s*\}, \[focusPlan\]\);/);
});

test("a sheet's Escape: back, except in a dialog, on the place search, or when already handled", () => {
  type Fake = SheetKeyEvent & { prevented: boolean };
  const event = (key: string, opts: { prevented?: boolean; inDialog?: boolean; role?: string; noTarget?: boolean } = {}): Fake => {
    const e: Fake = {
      key,
      defaultPrevented: opts.prevented ?? false,
      prevented: false,
      target: opts.noTarget
        ? null
        : {
            closest: (selector: string) => (selector === "dialog" && opts.inDialog ? {} : null),
            getAttribute: (name: string) => (name === "role" ? (opts.role ?? null) : null),
          },
      preventDefault() {
        e.prevented = true;
      },
    };
    return e;
  };
  const run = (e: Fake) => {
    let back = 0;
    const went = sheetEscape(e, () => back++);
    return { went, back, prevented: e.prevented };
  };
  const goes = { went: true, back: 1, prevented: true };
  const stays = { went: false, back: 0, prevented: false };
  assert.deepEqual(run(event("Escape")), goes);
  assert.deepEqual(run(event("Escape", { noTarget: true })), goes);
  assert.deepEqual(run(event("Escape", { role: "button" })), goes);
  assert.deepEqual(run(event("Enter")), stays);
  assert.deepEqual(run(event("Escape", { prevented: true })), stays, "already handled");
  assert.deepEqual(run(event("Escape", { inDialog: true })), stays, "the weight dialog's own Escape");
  assert.deepEqual(run(event("Escape", { role: "combobox" })), stays, "the place search's list");
});

test("the Map layers sheet holds the switches in 312's order, then the full legend with its junctions", () => {
  const sheet = app.slice(app.indexOf('id="sheet-layers"'), app.indexOf('id="sheet-gpx"'));
  // Traffic stress, high-stress lanes, high contrast, federal land, rail stations (OWNER-DECISIONS 312).
  const parts = [
    "Show traffic stress on the map",
    "<HighStressLanesSwitch",
    "<AccessibilitySwitch",
    "<FederalLandFor",
    "<RailStationsSection",
    "<StressLegend",
    "<JunctionLegend />",
  ];
  const at = parts.map((part) => sheet.indexOf(part));
  assert.ok(at.every((i) => i > 0), JSON.stringify(at));
  assert.deepEqual(at, [...at].sort((a, b) => a - b));
  assert.match(sheet, /\{!federalShown\(preset, true\) && <p className="hint mass-ride-layers">\{MASS_RIDE_LAYERS_NOTE\}<\/p>\}/);
  assert.equal(MASS_RIDE_LAYERS_NOTE, "Mass Ride has its own layers, such as federal land.");
  assert.match(sheet, /<StressLegend facilities=\{facilitiesShown\} zoom=\{zoom\} shown=\{stressVisible\} foldedZoom \/>/);
  assert.match(app, /id="sheet-gpx"[\s\S]*<GpxPanel/);
  assert.match(app, /federalVisible=\{federalShown\(preset, federalOn\)\}/, "federal land stays Mass Ride's (324)");
});

test("the legend's Junctions: the markers' own triangle and diamond, each with its words", () => {
  const html = renderToStaticMarkup(createElement(JunctionLegend));
  assert.match(html, /<h4 id="junction-legend-heading">Junctions<\/h4><ul class="junction-legend-list" aria-labelledby="junction-legend-heading">/);
  assert.match(html, /M12 2\.5 22\.5 20\.5H1\.5Z" fill="#f59e0b"[\s\S]*?Higher stress<span class="hint"> \(triangle\)/);
  assert.match(html, /M12 1\.5 22\.5 12 12 22\.5 1\.5 12Z" fill="#dc2626"[\s\S]*?Very high stress<span class="hint"> \(diamond\)/);
  assert.equal((html.match(/<span class="junction-icon" aria-hidden="true">/g) ?? []).length, 2, "the icons are decoration; the words carry it");
});

test("the zoom explanations are behind 'What each zoom level shows'; the zoom notice stays in view", () => {
  const folded = renderToStaticMarkup(createElement(StressZoomNotes, { zoom: 11, shown: true, folded: true }));
  // The notice's words are zoomed-trails' (stressZoomNotice); here only where it sits.
  assert.ok(folded.startsWith(`<p class="notice" role="status">${stressZoomNotice(11, true)}</p>`), folded.slice(0, 120));
  assert.match(folded, new RegExp(`<details class="fold zoom-notes"><summary>${ZOOM_LEVELS_LINK}</summary>`));
  assert.ok(folded.indexOf("<details") < folded.indexOf("The map is at zoom 11."), "the long text is inside the disclosure");
  assert.ok(folded.includes(CAR_FREE_NOTE));
  // Unfolded, as before: no disclosure.
  assert.doesNotMatch(renderToStaticMarkup(createElement(StressZoomNotes, { zoom: 11, shown: true })), /<details/);
});

test("the parts the owner decided OFF (384) are built, and off: the zoom notice and the High contrast shortcut in the planner", () => {
  assert.deepEqual(PLANNER_EXTRAS, { zoomNotice: false, highContrastShortcut: false });
  // A live region kept in the page, so a change is said (recheck: the sheet's copy is hidden while the planner shows).
  assert.equal(
    renderToStaticMarkup(createElement(PlannerZoomNotice, { zoom: 11, shown: true })),
    `<div class="planner-zoom" role="status"><p class="notice">${stressZoomNotice(11, true)}</p></div>`,
  );
  assert.equal(renderToStaticMarkup(createElement(PlannerZoomNotice, { zoom: 16, shown: true })), '<div class="planner-zoom" role="status"></div>');
  const shortcut = renderToStaticMarkup(createElement(HighContrastShortcut, { on: true, onChange: () => {} }));
  const described = /<button type="button" class="secondary high-contrast-shortcut" aria-pressed="true" aria-describedby="([^"]+)">High contrast<span aria-hidden="true">: On<\/span><\/button><span id="([^"]+)" class="visually-hidden">([^<]+)<\/span>/.exec(shortcut);
  assert.ok(described, shortcut);
  assert.equal(described[1], described[2], "described by its hint");
  assert.equal(described[3].replace(/&#x27;/g, "'"), ACCESSIBILITY_HINT);
  const fromLink = renderToStaticMarkup(createElement(HighContrastShortcut, { on: false, paletteFromAddress: true, onChange: () => {} }));
  assert.ok(fromLink.replace(/&#x27;/g, "'").includes(`${ACCESSIBILITY_HINT} ${ACCESSIBILITY_ADDRESS_NOTE}`), "the from-link note, as the sheet's switch shows it");
  assert.match(app, /\{PLANNER_EXTRAS\.zoomNotice && <PlannerZoomNotice/);
  assert.match(app, /\{PLANNER_EXTRAS\.highContrastShortcut && \(\s*<HighContrastShortcut on=\{accessibilityOn\(\)\} paletteFromAddress=\{paletteSetByAddress\(\)\}/);
});

// ---- the font and the stylesheet ------------------------------------------------

test("Atkinson Hyperlegible: fonts/fonts.css, relative url()s for Vite's /assets/, imported, with the files beside it", () => {
  const fonts = src("../fonts/fonts.css");
  const faces = [...fonts.matchAll(/@font-face \{([^}]*)\}/g)].map((m) => m[1]);
  assert.equal(faces.length, 2);
  const urls = faces.flatMap((face) => [...face.matchAll(/url\("([^"]+)"\)/g)].map((m) => m[1]));
  // Relative, so Vite fingerprints them into /assets/, which both edges serve (operations SF1); never /fonts/.
  assert.deepEqual(urls.sort(), ["./atkinson-hyperlegible-bold.woff2", "./atkinson-hyperlegible-regular.woff2"]);
  for (const face of faces) {
    assert.match(face, /font-display: swap/);
    assert.match(face, /src:\s*local\(/, "an installed font first: nothing to download");
  }
  assert.doesNotMatch(css, /@font-face|url\("?\/fonts\//, "styles.css asks for no font file");
  // The switch: main.tsx imports fonts.css exactly when both files are in src/fonts/ (no request, no 404, today).
  const main = src("../main.tsx");
  const files = ["regular", "bold"].map((w) => existsSync(new URL(`../fonts/atkinson-hyperlegible-${w}.woff2`, import.meta.url)));
  const imported = /^import "\.\/fonts\/fonts\.css";$/m.test(main);
  assert.equal(files[0], files[1], "both font files, or neither");
  assert.equal(imported, files[0], imported ? "fonts.css is imported but the font files are missing" : "the font files are there but fonts.css is not imported");
  assert.ok(imported && files[0] && files[1], "the font is switched on (OWNER-DECISIONS 384)");
  assert.match(main, /import "\.\/styles\.css";\s*import "\.\/fonts\/fonts\.css";/, "after styles.css");
  if (imported) assert.ok(existsSync(new URL("../fonts/OFL.txt", import.meta.url)), "the SIL Open Font License ships with the files");
  assert.match(css, /--font: "Atkinson Hyperlegible", system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif;/);
  assert.match(css, /font-family: var\(--font\);/);
  // font-src 'self': no font service, no external URL anywhere in the stylesheets or the page.
  for (const sheet of [css, fonts]) assert.doesNotMatch(sheet, /fonts\.googleapis|fonts\.gstatic|https?:\/\/[^"')]*\.(woff2?|ttf|otf)/);
  assert.doesNotMatch(src("../../index.html"), /googleapis|gstatic|<link[^>]*font/i);
});

test("the sidebar's own buttons and summaries are 44 px high at least", () => {
  assert.match(css, /\.panel button,\s*\.panel summary \{\s*min-height: 44px;/);
  assert.match(css, /\.panel \.bar-button \{[^}]*min-height: 56px/);
  // Five buttons (OWNER-DECISIONS 392): five columns; at a phone's width the words wrap, 48 px high, and the Back button is 44 px.
  assert.match(css, /\.bottom-bar \{[^}]*grid-template-columns: repeat\(auto-fit, minmax\(3\.5rem, 1fr\)\)/);
  assert.match(css, /@media \(max-width: 720px\) \{[\s\S]*?\.panel \.bar-button \{[^}]*min-height: 48px;[^}]*overflow-wrap: break-word/);
  assert.doesNotMatch(css, /@media \(max-width: 720px\) \{[\s\S]*?\.panel \.bar-button \{[^}]*flex-direction: row/, "icon over words, not beside them, at five across");
  assert.match(css, /\.sheet-back \{[^}]*min-width: 44px;[^}]*min-height: 44px/);
  assert.match(css, /\.sheet-header \{[^}]*flex-wrap: wrap/);
  assert.match(css, /\.ride-line-button \{[^}]*min-height: 56px/);
  assert.match(css, /\.sheet-back \{[^}]*min-width: 44px/);
});

test("the folds show open or closed, the plain buttons have a 3:1 edge, and focus rings are not clipped", () => {
  assert.match(css, /details\.fold > summary::before \{[^}]*border-right: 2px solid currentColor;[^}]*transform: rotate\(-45deg\);/);
  assert.match(css, /details\.fold\[open\] > summary::before \{\s*transform: rotate\(45deg\);/);
  assert.match(css, /button\.secondary,\s*\.route-actions button\.secondary \{[^}]*border-color: var\(--swatch-border\);/);
  assert.match(css, /\.point-tools button \{[^}]*border-color: var\(--swatch-border\);/);
  assert.match(css, /\.sheet-back \{[^}]*border-color: var\(--swatch-border\);/);
  assert.match(css, /\.panel \.ride-line-button:focus-visible,\s*\.panel \.bar-button:focus-visible \{\s*outline-offset: -3px;/);
  assert.match(css, /@media \(forced-colors: active\) \{\s*\.panel \.bar-button,\s*\.panel \.ride-line-button \{\s*border: 1px solid ButtonText;/);
});

test("short or zoomed screens: the whole panel scrolls as one, so nothing pinned crowds out the planner or the banner", () => {
  const start = css.indexOf("@media (max-height: 32.5em), (max-width: 22.5em) {");
  assert.ok(start > 0, "the rule is there");
  const rule = css.slice(start, css.indexOf("\n}\n", start));
  assert.match(rule, /\.panel \{\s*overflow-y: auto;/);
  assert.match(rule, /\.panel-body,\s*\.panel-scroll \{\s*flex: none;\s*min-height: auto;\s*overflow: visible;/);
  // The banner stays the first thing, and nothing moves it or hides it (mutation NIT 2).
  // Not moved, not hidden: display, visibility and opacity too (the mutation re-check's NIT C).
  // Whitespace-tolerant, and any opacity under 1 counts.
  for (const rule of css.matchAll(/\.beta-banner[^{]*\{([^}]*)\}/g)) {
    const body = rule[1];
    assert.doesNotMatch(body, /(^|[\s;])order\s*:|display\s*:\s*none|visibility\s*:\s*(hidden|collapse)/, rule[0]);
    for (const o of body.matchAll(/opacity\s*:\s*([\d.]+)/g)) assert.ok(parseFloat(o[1]) >= 1, `opacity ${o[1]} in ${rule[0]}`);
  }
  assert.doesNotMatch(css, /\.panel-scroll[^{]*\{[^}]*\border:/);
  assert.doesNotMatch(css, /\.panel-footer/, "the old footer's rules are gone with it");
  // The scroll to the top reaches whichever scrolls.
  assert.match(app, /panelBodyRef\.current\?\.scrollTo\(\{ top: 0 \}\);\s*panelRef\.current\?\.scrollTo\?\.\(\{ top: 0 \}\);/);
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
  // The route's live region is outside the panel, so a bar sheet or the phone's hidden sheet does not
  // silence it (the reviews' S1, S2); the visible copy in the planner is hidden from screen readers.
  const region = app.indexOf('<div role="status" aria-live="polite" className="status-line visually-hidden">');
  assert.ok(region > 0 && region < app.indexOf("<aside"), "before the panel, outside it");
  assert.match(app.slice(region, app.indexOf("<aside")), /\{status\.kind === "ok" && routeSaid && <p>\{routeSaid\}<\/p>\}/);
  assert.match(app, /<div className="status-shown" aria-hidden="true">/);
  // "No route yet." is read where it stands, and is not in the live region (recheck N-new-2).
  assert.doesNotMatch(app.slice(region, app.indexOf("<aside")), /No route yet/);
  const shownCopy = app.slice(app.indexOf('<div className="status-shown"'));
  assert.doesNotMatch(shownCopy.slice(0, shownCopy.indexOf("</div>")), /No route yet/);
  assert.match(app, /\{status\.kind === "idle" && points\.length < 2 && <p className="hint">No route yet\.<\/p>\}/);
  assert.equal((app.match(/aria-live="polite" className="status-line/g) ?? []).length, 1);
  assert.match(app, /\{said\.text\}/);
  assert.match(app, /announce\(addedSaid\(next\.indexOf\(point\), next\.length, loopVias\)\)/);
});

test("on a desktop the points come first, then the Ride line, then the route; on a phone the route leads", () => {
  assert.deepEqual(sheetOrder(false, "idle", false), ["points", "presets", "route"]);
  assert.deepEqual(sheetOrder(false, "ok", true), ["points", "presets", "route"]);
  assert.deepEqual(sheetOrder(true, "ok", true), ["route", "points", "presets"]);
  assert.deepEqual(sheetOrder(true, "idle", false), ["points", "presets", "route"]);
});

// ---- OWNER-DECISIONS 384: App's dispatch, the bar's current button, the Settings sheet ----------------

test("App dispatches the focus decision to the right element (the mutation re-check's NIT A)", () => {
  const effect = app.slice(app.indexOf("const target = focusOnViewChange("), app.indexOf("}, [view, legendTarget]);"));
  assert.match(effect, /if \(target\.kind === "bar"\) barButtons\.current\[target\.id\]\?\.focus\(\);/);
  assert.match(effect, /else if \(target\.kind === "error"\) errorRef\.current\?\.focus\(\);/);
  assert.match(effect, /else if \(target\.kind === "plan"\) planButtonRef\.current\?\.focus\(\);/);
  assert.match(effect, /const heading = target\.legend \? legendHeadingRef : \{ layers: layersHeadingRef, gpx: gpxHeadingRef, settings: settingsHeadingRef \}\[target\.view\];/);
  // Legend opens Map layers at its legend; the others do not.
  assert.match(app, /setLegendTarget\(item\.toLegend === true\);/);
  assert.match(app, /<BottomBar view=\{view\} legend=\{legendTarget\} onOpen=\{openSheet\}/);
});

test("the bar's current button: the sheet showing, and of Map layers and Legend only the one that opened it", () => {
  const views: PanelView[] = ["planner", "layers", "gpx", "settings"];
  for (const view of views)
    for (const legend of [false, true])
      for (const item of BAR_ITEMS) {
        const want = view === item.opens && (item.id === "legend" ? legend : item.id === "layers" ? !legend : true);
        assert.equal(barCurrent(item, view, legend), want, `${view} legend=${legend} ${item.id}`);
      }
  // Plan (OWNER-DECISIONS 392) is the current one while the planner shows, and only then.
  const plan = BAR_ITEMS[0];
  for (const legend of [false, true]) {
    assert.equal(barCurrent(plan, "planner", legend), true);
    for (const view of ["layers", "gpx", "settings"] as const) assert.equal(barCurrent(plan, view, legend), false);
    for (const item of BAR_ITEMS.slice(1)) assert.equal(barCurrent(item, "planner", legend), false, `${item.id} is not current on the planner`);
  }
  assert.match(sidebar, /const current = barCurrent\(item, view, legend\);/);
  assert.match(sidebar, /aria-current=\{current \? "true" : undefined\}/);
});

test("the Settings sheet (384): a Display group with the High contrast switch, then the sign-in note; one state, unique ids", () => {
  const sheet = app.slice(app.indexOf('id="sheet-settings"'), app.indexOf("{/* Pinned under"));
  assert.match(sheet, /title=\{SHEET_TITLES\.settings\}\s+open=\{view === "settings"\}\s+onBack=\{backToPlanner\}\s+headingRef=\{settingsHeadingRef\}/);
  assert.match(sheet, /<section aria-labelledby="settings-display-heading">\s*<h3 id="settings-display-heading">Display<\/h3>/);
  // The sign-in note has its own heading, so heading navigation does not file it under Display.
  assert.match(sheet, /<section aria-labelledby="settings-signin-heading">\s*<h3 id="settings-signin-heading">Signing in<\/h3>\s*<p className="hint">/);
  assert.ok(sheet.indexOf("settings-display-heading") < sheet.indexOf("settings-signin-heading"));
  assert.match(sheet, /<AccessibilitySwitch\s+idBase="settings-contrast"\s+on=\{accessibilityOn\(\)\}\s+source=\{accessibilitySource\(\)\}\s+paletteFromAddress=\{paletteSetByAddress\(\)\}\s+onChange=\{\(on\) => setAccessibility\(on\)\}/);
  assert.ok(sheet.indexOf("Display") < sheet.indexOf("sign in with Discord"), "the sign-in note is still there, after the display group");
  assert.match(sheet, /rememberPlan\(session\(\), window\.location\.hash\)/);
  assert.doesNotMatch(app, /sheet-about|aboutHeadingRef|"about"/);
  // Both copies read the one module state, so a flip in either shows in both; their ids differ.
  const layers = app.slice(app.indexOf('id="sheet-layers"'), app.indexOf('id="sheet-gpx"'));
  assert.match(layers, /<AccessibilitySwitch\s+on=\{accessibilityOn\(\)\}/);
  const a = renderToStaticMarkup(createElement(AccessibilitySwitch, { on: true, source: "chosen", paletteFromAddress: false, onChange: () => {} }));
  const b = renderToStaticMarkup(createElement(AccessibilitySwitch, { idBase: "settings-contrast", on: true, source: "chosen", paletteFromAddress: false, onChange: () => {} }));
  const ids = (html: string) => [...html.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(ids(a), ["a11y-switch", "a11y-label", "a11y-hint"]);
  assert.deepEqual(ids(b), ["settings-contrast-switch", "settings-contrast-label", "settings-contrast-hint"]);
  assert.ok(b.includes('aria-labelledby="settings-contrast-label"') && b.includes('aria-describedby="settings-contrast-hint"'));
  assert.ok(b.includes(">High contrast</span>"));
  assert.equal(new Set([...ids(a), ...ids(b)]).size, 6, "no id twice in the page");
});

test("High contrast (384): the words say what it does and name no disability; the identifiers and the link are as they were", () => {
  assert.equal(ACCESSIBILITY_LABEL, "High contrast");
  assert.equal(ACCESSIBILITY_HINT, "Bolder lines, stronger borders and text, and colors that don't rely on red and green. Kept in this browser.");
  for (const text of [ACCESSIBILITY_LABEL, ACCESSIBILITY_HINT, ACCESSIBILITY_ADDRESS_NOTE, ACCESSIBILITY_CONTRAST_NOTE, BAR_ITEMS.map((i) => i.description).join(" ")])
    assert.doesNotMatch(text, /accessib|colou?r.?blind|disab|impair|blind/i, text);
  // No visible word anywhere in the app's text still says "Accessibility" for the switch.
  assert.doesNotMatch(app, />\s*Accessibility\s*</);
  assert.equal(ACCESSIBILITY_CLASS, "a11y", "the root class is unchanged");
  assert.equal(ACCESSIBILITY_STORAGE_KEY, "routemaker.accessibility", "what a browser remembers is unchanged");
});

test("Settings (384): theme follows the system, the planner zoom notice stays off; both decided", () => {
  assert.equal(PLANNER_EXTRAS.zoomNotice, false);
  assert.equal(PLANNER_EXTRAS.highContrastShortcut, false);
  assert.doesNotMatch(css, /data-theme|\.theme-toggle/, "no theme switch: the panel follows prefers-color-scheme");
  assert.match(css, /@media \(prefers-color-scheme: dark\)/);
});
