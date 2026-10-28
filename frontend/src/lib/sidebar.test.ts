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
import { hillsWords, startDials, type Dials } from "./dials.ts";
import { hillsShort, rideSummary, rideSummarySpoken, settingsSummary, settingsSummarySpoken, targetShort, trafficShort, whenShort } from "./rideSummary.ts";
import { NOT_AVAILABLE, busyMetres, calmPercent, calmWayShares, calmWaysLabel, calmWaysText, calmWords, groupRideLine, heavyMetres, turnTotal, junctionFigure, quickFigures, stressBarKey, stressBarLabel, stressPlainParts } from "./quickFigures.ts";
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
  chartFoldOpen,
  SHEET_TITLES,
  copyText,
  focusOnViewChange,
  foldTitle,
  linkSaidFor,
  linkSpokenFor,
  linkToCopy,
  noticeSaidElsewhere,
  rescueCompactFocus,
  rideActionLabel,
  searchLede,
  sheetEscape,
  popupBackLabel,
  POPUP_VIEWS,
  sayInPopup,
  listenForPopupSay,
  openOnto,
  backFrom,
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
import { appSource } from "../testSupport/appSource.mjs";

const src = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");
const app = appSource();
const sidebar = src("../Sidebar.tsx");
const css = src("../styles.css");

// ---- the Ride line ----------------------------------------------------------

test("the Ride line: the mockup's words for a Default ride, ride type first", () => {
  assert.equal(rideSummary("default", startDials("default")), "Default · quiet streets · hills up to 8% · now");
  assert.equal(rideSummarySpoken("default", startDials("default")), "Default, quiet streets, hills up to 8%, now");
});

test("the Ride line follows the sliders, the ride time, the loop and gravel; and names a moved ride Custom", () => {
  const dials: Dials = { ...startDials("default", null, "weekend"), stress: 100, hills: -90, loop: true, avoidGravel: true };
  assert.equal(
    rideSummary("default", dials),
    "Custom (based on Default) · calmest · hills up to 2% · weekend · loop · avoids gravel",
  );
  assert.equal(whenShort("weekday_rush"), "weekday rush");
  assert.equal(whenShort("weekday_offpeak"), "weekday off-hours");
  assert.equal(whenShort(null), "now");
  // AM and PM keep their capitals, which a screen reader says as letters.
  assert.equal(whenShort("night"), "night, 9 PM to 7 AM");
});

test("every slider position has words, and Mass Ride's locked slider says what it is", () => {
  for (let stress = 0; stress <= 100; stress += 5) assert.ok(trafficShort(stress).length > 0);
  for (let hills = -100; hills <= 100; hills += 5) assert.ok(hillsShort(hills, false).length > 0 && hillsShort(hills, true).length > 0);
  // The words change where stressWords and hillsWords change (mutation NIT 1: each edge, both sides).
  const traffic: Array<[number, string]> = [
    [10, "traffic tolerant"], [11, "direct"], [29, "direct"], [30, "balanced traffic"], [50, "balanced traffic"],
    [51, "quiet streets"], [74, "quiet streets"], [75, "low stress"], [80, "low stress"], [81, "calm"], [94, "calm"], [95, "calmest"],
  ];
  for (const [stress, words] of traffic) assert.equal(trafficShort(stress), words, `traffic ${stress}`);
  // The hills chip says the grade, as the slider does (review N1: "Easy up to 8%" on the slider, "hills up to 8%" here).
  for (let value = -100; value <= 100; value += 1) {
    for (const climbs of [false, true]) {
      const slider = hillsWords(value, climbs);
      assert.equal(hillsShort(value, climbs), slider.startsWith("Easy ") ? `hills ${slider.slice(5)}` : slider.toLowerCase(), `hills ${value}`);
    }
  }
  const hills: Array<[number, string]> = [
    [-100, "hills up to 1%"], [0, "hills up to 8%"], [10, "hills up to 9%"], [11, "some extra climbing"], [79, "some extra climbing"], [80, "seeks hills"],
  ];
  for (const [value, words] of hills) assert.equal(hillsShort(value, true), words, `hills ${value}`);
  // Right of the middle on every ride type but Mountain Goat: the grade goes on up (OWNER-DECISIONS 242).
  const tolerant: Array<[number, string]> = [[11, "hills up to 9%"], [40, "hills up to 11%"], [100, "hills up to 15%"]];
  for (const [value, words] of tolerant) assert.equal(hillsShort(value, false), words, `hills ${value}`);
  assert.match(rideSummary("ebike", startDials("ebike")), /^E-bike · quiet streets · hills up to \d+% · now$/);
  assert.match(rideSummary("mountain-goat", startDials("mountain-goat")), / · seeks hills · /);
  assert.match(rideSummary("default", { ...startDials("default"), assist: true }), /^Default, electric assist · /);
  assert.match(rideSummary("mass-ride", startDials("mass-ride")), /^Mass Ride · most direct roadway · hills up to \d+% · now$/);
  // A loop set on a Mass Ride is hidden there (374): the summary does not say it.
  assert.doesNotMatch(rideSummary("mass-ride", { ...startDials("mass-ride"), loop: true }), /loop/);
  // Cargo says its load.
  assert.match(rideSummary("cargo", startDials("cargo", "people")), /^Cargo Bike, cargo with passengers · /);
});

test("the Ride line says a set target distance, miles first, after when (312's order)", () => {
  assert.equal(targetShort(undefined), null);
  assert.equal(targetShort(32187), "about 20.0 mi (32.2 km)");
  const dials: Dials = { ...startDials("default"), targetDistanceM: 32187, loop: true };
  assert.equal(rideSummary("default", dials), "Default · quiet streets · hills up to 8% · now · about 20.0 mi (32.2 km) · loop");
  assert.equal(rideSummarySpoken("default", dials), "Default, quiet streets, hills up to 8%, now, about 20.0 mi (32.2 km), loop");
});

test("the Ride line never carries the rider and bike weight (313-314): not a figure, not the dial", () => {
  const withWeight: Dials = { ...startDials("default"), systemWeightKg: 123 };
  assert.equal(rideSummary("default", withWeight), rideSummary("default", startDials("default")));
  assert.doesNotMatch(rideSummary("default", withWeight), /123|lb|kg|weight/i);
  assert.doesNotMatch(src("./rideSummary.ts").replace(/\/\*[\s\S]*?\*\//g, ""), /systemWeight|weight/i);
});

test("the Ride line is a heading holding a button with aria-expanded, whose words are read with commas", () => {
  const html = renderToStaticMarkup(
    createElement(RideSettings, {
      summary: "quiet streets · now",
      spoken: "quiet streets, now",
      typeCard: createElement("div", { className: "type-card" }, "Default"),
      children: createElement("p", null, "controls"),
    }),
  );
  // The region is named "Ride" alone, not by the whole button (the a11y review's N4); the ride type's own button
  // comes first (edit-route redesign, Stephen 2026-10-18), then the line.
  assert.match(
    html,
    /^<section class="ride-settings" aria-label="Ride"><div class="type-card">Default<\/div><h2 id="ride-settings-heading" class="ride-line"><button type="button" class="ride-line-button" aria-expanded="false" aria-controls="[^"]+">/,
  );
  // Labelled Ride settings; the sliders' summary shown as chips and heard as one sentence with commas.
  assert.match(
    html,
    /<span class="ride-line-label">Ride settings<\/span><span class="ride-line-summary" aria-hidden="true"><span class="ride-chip">quiet streets<\/span><span class="ride-chip">now<\/span><\/span><span class="visually-hidden">: quiet streets, now\.<\/span>/,
  );
  // Shown Adjust or Done, heard Adjust whatever the state: aria-expanded says it (no "Done, expanded": N8). Closed,
  // the word is there once, shown and heard (P10: not "Adjust Adjust"); open, "Done" is shown and "Adjust" heard.
  assert.match(html, /<span class="ride-line-action"> Adjust<\/span><\/button>/);
  assert.doesNotMatch(html, /Adjust<\/span><span class="visually-hidden"> Adjust/);
  const parts = readFileSync(new URL("./sidebarParts.ts", import.meta.url), "utf8");
  assert.match(parts, /h\("span", \{ key: "shown", className: "ride-line-action", "aria-hidden": "true" \}, rideActionLabel\(open\)\),\s*h\("span", \{ key: "said", className: "visually-hidden" \}, ` \$\{RIDE_ACTION_SPOKEN\}`\),/);
  assert.equal(rideActionLabel(false), "Adjust");
  assert.equal(rideActionLabel(true), "Done");
  assert.equal(RIDE_ACTION_SPOKEN, "Adjust");
  // The controls stay in the page while closed, so nothing they hold is lost.
  assert.match(html, /<div id="[^"]+" class="ride-settings-body" hidden=""><p>controls<\/p><\/div>/);
});

test("App puts the ride type's button first and every dial behind the Ride settings line, in the mockup's order", () => {
  // The ride type is one press from its list (edit-route redesign); Go's Ride sheet lists them itself (typeCard false).
  assert.match(
    app,
    /<RideSettings key="presets" summary=\{settingsSummary\(preset, dials\)\} spoken=\{settingsSummarySpoken\(preset, dials\)\} typeCard=\{presetsSection\}>\s*<DialsPanel/,
  );
  assert.match(app, /const presetsSection = typeCard \? <RideTypePicker key="presets" preset=\{preset\} dials=\{dials\} onChoose=\{choosePreset\} \/> : null;/);
  assert.match(src("../App.tsx"), /typeCard: mode !== "go",/);
  assert.equal(settingsSummary("default", startDials("default")), "quiet streets · hills up to 8% · now");
  assert.equal(settingsSummarySpoken("default", startDials("default")), "quiet streets, hills up to 8%, now");
  const dials = src("../DialsPanel.tsx");
  const at = (text: string) => {
    const i = dials.indexOf(text);
    assert.ok(i > 0, text);
    return i;
  };
  const order = [
    'label={t("Traffic")}',
    'label={t("Hills")}',
    '<legend>{t("When")}</legend>',
    "{view.target && (",
    "Avoid gravel",
  ].map(at);
  assert.deepEqual(order, [...order].sort((a, b) => a - b), "Traffic, Hills, When, target distance, gravel");
  // "Make it a loop" is no longer behind the Edit button (OWNER-DECISIONS 388): it is by the search, in the Points section.
  assert.doesNotMatch(dials, /loopView|withLoop|type="checkbox"\s+checked=\{loop/, "the dials panel has no loop toggle");
  const points = app.slice(app.indexOf("const pointsSection ="), app.indexOf("const routeSection ="));
  const inPoints = (text: string) => {
    const i = points.indexOf(text);
    assert.ok(i > 0, text);
    return i;
  };
  // UI-CLEANUP (the mockup's "Points Swap Loop Edit Info"): the loop box in the Points heading's row, then the
  // boxes and the points (Plan streamline, 2026-10-17: From, the points, To, then Add a stop with Best order).
  assert.ok(inPoints("{loop && (") < inPoints("<PointBoxes"), "the loop box, then the boxes and the points");
  const planner = src("../app/Planner.tsx");
  const boxes = planner.slice(planner.indexOf("function PointBoxes("), planner.indexOf("export interface RideSectionProps"));
  const inBoxes = (text: string) => {
    const i = boxes.indexOf(text);
    assert.ok(i > 0, text);
    return i;
  };
  const steps = ['{showFrom && editing === null && search("from")}', "{searchLede(loopVias, accessMode)}", "<PointsList", '{showTo && editing === null && search("to")}', 'search("add")}', "{BEST_ORDER_LABEL}"].map(inBoxes);
  assert.deepEqual(steps, [...steps].sort((a, b) => a - b), "From, the points, To, Add a stop, Best order");
  // The map-center actions are in Map tools by the zoom buttons, not the planner (OWNER-DECISIONS 450).
  assert.doesNotMatch(points, /Add point at map center|Road info at map center/);
  assert.ok(inPoints("{loop && (") < src("../app/Planner.tsx").indexOf('<div id="points-search"'), "outside the part that hides while the points compact");
  assert.match(points, /aria-describedby=\{loopHintId\}/);
  assert.match(app, /const loopHintId = useId\(\);/, "a generated id, not a fixed one");
  // The hint is plain visible text: a paragraph with the id the box points at, and no live region or hidden class on it.
  // Shown while the box is checked (what a loop needs next); its description either way.
  // The box's description, said and not shown (Stephen 2026-10-20: "it needs to be simpler").
  assert.match(points, /<p className="visually-hidden loop-hint" id=\{loopHintId\}>\s*\{loop\.hint\}\s*<\/p>/);
  assert.match(points, /commitDials\(withLoop\(dials, event\.target\.checked\)\)/, "its change goes through the announcing commit");
  assert.match(app, /const loop = loopView\(preset, dials\.loop, points\);/);
  // The weight row moved to Settings (the owner, 2026-10-18): status only, Change opening the private dialog.
  assert.doesNotMatch(dials, /WeightSetting/);
  assert.match(src("../app/Sheets.tsx"), /<WeightSetting \{\.\.\.props\.weight\} \/>/);
});

// ---- points first ------------------------------------------------------------

test("the points come first, the how-to is behind Points' Info, Swap and Undo beside the heading, and Clear behind More", () => {
  assert.equal(MORE_TIPS, "More tips");
  assert.equal(FEWER_TIPS, "Fewer tips");
  // The keyboard's way in stays in view (the a11y review's S6).
  assert.equal(searchLede(false, true), "Search, click the map, or use Add point at map center in Map tools: start, then end. Later clicks add stops.");
  assert.equal(searchLede(true, true), "Search, click the map, or use Add point at map center in Map tools: start, then stops. The ride comes back to the start.");
  // The start-up how-to only before any point; with points, how to change them (the correctness review's N5).
  // UI-CLEANUP: behind the Info button in the Points heading's row (the mockup's "Points Swap Loop Edit Info").
  assert.match(
    app,
    /className="tips-body more-tips" hidden=\{!tips\}>[\s\S]{0,500}<HintLines lines=\{points\.length > 0 \? editingTips\(accessMode, touch\) : emptyPlanHint\(preset, loopVias, accessMode, touch\)\} \/>/,
  );
  assert.match(app, /className="secondary icon-button tips-toggle" aria-expanded=\{tips\} aria-controls=\{tipsId\} onClick=\{\(\) => setTips\(!tips\)\}/);
  // Every existing button is still there: Swap, Undo and Redo in the heading's row, Info last (Plan streamline,
  // 2026-10-17), where Plan's bar is not (P10: the bar holds them in Plan, one set per layout); Reset in the plan
  // panel, Clear the bar's trash. Add point at map center is in Map tools (450).
  const row = ["swap-points", 'data-history="undo"', 'data-history="redo"', "tips-toggle"].map((t) => app.indexOf(t));
  assert.ok(row.every((i) => i > 0));
  assert.deepEqual(row, [...row].sort((a, b) => a - b));
  assert.match(app, /\{historyHere && \(\s*<button type="button" className="secondary icon-button" data-history="undo"/);
  assert.match(src("../App.tsx"), /historyHere: !narrow && !planFirst,/);
  const panel = src("../app/PlanPanel.tsx");
  assert.ok(panel.includes("{RESET_LABEL}"));
  assert.ok(!panel.includes("{CLEAR_LABEL}"));
  assert.doesNotMatch(app, /className="actions point-add"|ref=\{addRef\}/);
  assert.match(app, /accessMode && !onBike \? \(\s*<MapTools\s+toggleRef=\{toolsToggleRef\}\s+onAddPoint=\{addAtCentre\}/);
  assert.equal(
    searchLede(false),
    "Search or click the map: start, then end. Later clicks add stops. For keyboard or screen reader use, turn on accessibility mode (the first button on the page, or in Settings).",
  );
  assert.equal(
    searchLede(true),
    "Search or click the map: start, then stops. The ride comes back to the start. For keyboard or screen reader use, turn on accessibility mode (the first button on the page, or in Settings).",
  );
  // I works only on the focused map: no button claims it (the a11y review's S2); the map's canvas still does.
  assert.doesNotMatch(app, /aria-keyshortcuts="I"/);
  const tools = src("../MapTools.tsx");
  assert.doesNotMatch(tools, /aria-keyshortcuts|role="menu|role="menuitem/, "a disclosure of plain buttons, not an ARIA menu");
  assert.match(tools, /aria-expanded=\{open\}\s+aria-controls=\{panelId\}/);
  assert.match(tools, /hidden=\{!open\}/);
  assert.match(src("../MapView.tsx"), /canvas\.setAttribute\("aria-keyshortcuts", "I"\)/);
  assert.match(app, /aria-describedby=\{reverseHint \? "reverse-hint" : "swap-hint"\}/);
  assert.match(app, /<p className="hint" id="reverse-hint">/);
});

test("with a route shown Plan's search and point tools stay in view (v0.7.0), and stay in the page", () => {
  // "Keep adding stops by search": no compacting and no Edit points; the plan panel holds the plan in words.
  assert.match(app, /const compactPoints = false;/);
  assert.doesNotMatch(app, /className="secondary icon-button edit-points"/);
  // The boxes are never hidden, so more stops can be added by search (v0.6.1 as well): From with no start, To with a
  // lone start, else Add a stop (Plan streamline, 2026-10-17).
  const planner = src("../app/Planner.tsx");
  assert.match(planner, /<div id="points-search" ref=\{pointsSearchRef\} className="points-controls plan-points">\s*\{showFrom && editing === null && search\("from"\)\}/);
  // A Change opens its box in that point's row (edit-route redesign, Stephen 2026-10-18).
  assert.match(planner, /index: editing,\s*node: \(\s*<div className="point-editor">\s*\{search\(changing === "from" \? "from" : "to"\)\}/);
  // Cancel puts the box away on a touch screen, as Escape does on a keyboard, and gives the focus to the row's Remove.
  assert.match(planner, /className="link point-cancel"\s*onClick=\{\(\) => \{\s*setChanging\(null\);\s*window\.setTimeout\(\(\) => removeRefs\.current\[editing\]\?\.focus\(\), 0\);/);
  assert.match(planner, /const showFrom = points\.length === 0 \|\| changing === "from";/);
  assert.match(planner, /const showTo = !showFrom && !loopVias && \(points\.length === 1 \|\| changing === "to"\);/);
  assert.match(planner, /const showAdd = !showFrom && !showTo && \(loopVias \? points\.length >= 1 : points\.length >= 2\);/);
  assert.match(app, /<div id="points-edit" ref=\{pointsEditRef\} hidden=\{compactPoints\}>/);
  // Clear, a plan from a link, or fewer than two points: the next route opens compact again (N1).
  assert.match(app, /const clearAll = \(\) => \{\s*setConfirmedKm\(null\);\s*setEditPoints\(false\);/);
  assert.match(app, /setEditPoints\(false\);\s*\/\/ A plan opened from a link opens drawn[^\n]*\n\s*forgetDrawn\(\);\s*setRouteAsk\(\(n\) => n \+ 1\);\s*setPoints\(VIA_MARKS\.nameAt\(VIA_MARKS\.markDrawn\(VIA_MARKS\.markAt\(plan\.points, plan\.vias\), plan\.drawn\), plan\.names\)\);/);
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
    { name: "a route arrives with the focus on a point tool (Reverse, Clear)", before: "addButton", wasCompact: false, compact: true, moves: true },
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
    /useLayoutEffect\(\(\) => \{\s*rescueCompactFocus\(\{\s*wasCompact: wasCompact\.current,\s*compact: compactPoints,\s*before: focusBeforeRender\.current,\s*hidden: \[pointsEditRef\.current\],\s*editPoints: editPointsRef\.current,\s*\}\);\s*wasCompact\.current = compactPoints;\s*\}, \[compactPoints\]\);/,
  );
  // After the sheet-order effect, which may first put the focus back on the (now hidden) element.
  assert.ok(app.indexOf("rescueCompactFocus({") > app.indexOf("}, [routeFirst]);"));
});

test("the points notice is said through the app's region while the planner is hidden, and only then (recheck S1)", () => {
  assert.equal(noticeSaidElsewhere("That point is outside the area this map covers.", false), true);
  assert.equal(noticeSaidElsewhere("That point is outside the area this map covers.", true), false, "the planner's own status says it");
  assert.equal(noticeSaidElsewhere(null, false), false);
  assert.equal(noticeSaidElsewhere("", false), false);
  // Go shows the notice in its sheet without a live region of its own: the app's region says it there.
  assert.match(app, /plannerShownNow\.current = view === "planner" && panelOpen && mode === "plan";/);
  assert.match(app, /if \(!saidAlready && noticeSaidElsewhere\(notice, plannerShownNow\.current\)\) announce\(notice as string\);\s*\}, \[notice, announce\]\);/);
});

test("a Mass Ride loads the federal-land data whatever the shading switch says, for the planner's list (recheck R-N1)", () => {
  assert.match(app, /federalWanted=\{federalShown\(preset, true\)/);
  const map = src("../MapView.tsx");
  assert.match(map, /if \(!\(visible \|\| callbacks\.current\.federalWanted\) \|\| federalLoading\) return;/);
  assert.match(map, /\}, \[props\.federalVisible, props\.federalWanted\]\);/);
});

test("Mass Ride's points on federal land: a warning on each row and marker, and the planner says when none is (item 239)", () => {
  const points = app.slice(app.indexOf("const federalAreas"), app.indexOf("const routeSection"));
  assert.match(points, /pointAreas\(points, federalData, federalShown\(preset, true\)\)/);
  assert.match(points, /area \? stopWarningShort\(area\) : null/);
  assert.match(points, /federalAreas\.every\(\(area\) => area === null\) && \(\s*<p className="hint federal-points">\{FEDERAL_POINTS_NONE\}<\/p>/);
  assert.match(points, /\{federalPlanner\}/);
  // Handed on to Plan's point boxes, which list them (Plan streamline, 2026-10-17).
  assert.match(points, /pointWarnings=\{pointWarnings\}/);
  assert.match(src("../app/Planner.tsx"), /onRemove=\{removeAt\}\s+warnings=\{pointWarnings\}/);
  assert.match(app, /pointWarnings=\{onBike \|\| reviewing \? undefined : pointWarnings\}/);
  // The Map layers sheet keeps its own list.
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

test("Go's stress line in plain words (the owner's P1): how calm, the paths and protected lanes, the busy road", () => {
  // The calm share is LTS 1 and 2 (calmPercent); busy is LTS 3, 4 and Avoid, as the detour notice says "busy roads (LTS 3-4)".
  assert.equal(calmWords({ "1": 900, "2": 100 }), "All calm");
  assert.equal(calmWords({ "1": 750, "2": 40, "4": 210 }), "Mostly calm", "the audit's route: LTS 1 75%, LTS 2 4%, LTS 4 21%");
  assert.equal(calmWords({ "1": 500, "3": 500 }), "Some busy roads");
  assert.equal(calmWords({ "1": 300, "4": 700 }), "Mostly busy");
  assert.equal(calmWords({}), null);
  assert.equal(calmWords({ "1": 1000, "3": 5 }), "All calm", "a few metres where the route meets a road are not said");
  assert.equal(busyMetres({ "2": 100, "3": 10, "4": 20, "5": 5 }), 35);
  assert.equal(calmWaysText({ path: 1300, protected: 500 }), "1.1 mi (1.8 km) on paths and protected lanes");
  assert.equal(calmWaysText({ path: 1300 }), "0.8 mi (1.3 km) on paths");
  assert.equal(calmWaysText({ protected: 805, path: 3 }), "0.5 mi (0.8 km) on protected lanes");
  assert.equal(calmWaysText({ lane: 900, none: 300 }), null, "a painted lane is neither");
  assert.equal(calmWaysText(undefined), null);
  // Each part left out where it is nothing.
  assert.deepEqual(stressPlainParts({ stress_m: { "1": 1500, "2": 60, "4": 322 }, facility_m: { path: 1300, protected: 500 } }), [
    "Mostly calm",
    "1.1 mi (1.8 km) on paths and protected lanes",
    "busy road for 0.2 mi (0.3 km)",
  ]);
  assert.deepEqual(stressPlainParts({ stress_m: { "1": 1000 }, facility_m: { none: 1000 } }), ["All calm"]);
  assert.deepEqual(stressPlainParts({ stress_m: {}, facility_m: undefined }), []);
  // The strip under the bar: the path, then the protected lane, as facilityRows has them; read as words.
  const shares = calmWayShares([
    { key: "path", metres: 1300, fraction: 0.6, percent: 60 },
    { key: "protected", metres: 500, fraction: 0.28, percent: 28 },
    { key: "lane", metres: 200, fraction: 0.1, percent: 10 },
    { key: "none", metres: 40, fraction: 0.02, percent: 2 },
  ]);
  assert.deepEqual(shares.map((s) => s.key), ["path", "protected"]);
  assert.equal(calmWaysLabel(shares), "Traffic-free paths: 0.8 mi (1.3 km), 60 percent; Protected bike lanes: 0.3 mi (0.5 km), 28 percent");
  assert.deepEqual(calmWayShares([{ key: "protected", metres: 0, fraction: 0, percent: 0 }]), []);
});

test("Go's stress figure: the bar and the strip are one button to the colour key; the shares stay the bar's name", () => {
  assert.match(app, /<figure className="stress stress-main stress-go" aria-labelledby="stress-figure-caption">/);
  assert.match(app, /<button type="button" className="stress-key-button" aria-describedby=\{keyHintId\} onClick=\{\(event\) => go\.onKey\?\.\(event\.currentTarget\)\}>\s*\{bar\}\s*\{strip\}/);
  assert.match(app, /<div className="stress-bar calm-ways" role="img" aria-label=\{calmWaysLabel\(ways\)\}>/);
  // Shown with " · ", said with commas; at peek said only.
  assert.match(app, /<span aria-hidden="true">\{parts\.join\(" · "\)\}<\/span>\s*<span className="visually-hidden">\{`\$\{parts\.join\(", "\)\}\.`\}<\/span>/);
  assert.match(app, /<StressFigure segments=\{segments\} line=\{groupLine\} go=\{\{ route, peek: go\.peek, onKey: go\.onStressKey \}\} \/>/);
  // A tap opens Layers, its Traffic stress section open (lib/layerSection.ts openAsk).
  assert.match(app, /onStressKey: \(opener: HTMLButtonElement\) => \{\s*setStressKeyAsk\(\(n\) => n \+ 1\);\s*openView\("layers", opener\);/);
  assert.match(app, /openAsk=\{stressKeyAsk\}/);
  const section = readFileSync(new URL("./layerSection.ts", import.meta.url), "utf8");
  assert.match(section, /useEffect\(\(\) => \{\s*if \(openAsk > 0\) setOpen\(true\);\s*\}, \[openAsk\]\);/);
});

test("the route's folds: Elevation and climbs, Stress and facilities, Directions, Junctions to watch, Other routes, Water and restrooms", () => {
  assert.equal(foldTitle("Junctions to watch", 4), "Junctions to watch (4)");
  assert.equal(foldTitle("Stress and facilities", null), "Stress and facilities");
  assert.equal(stepsCount(1), "1 step");
  assert.equal(stepsCount(12), "12 steps");
  // The edges (the mutation re-check's NIT B): a count of 0 is still said, as "(0)" and "0 steps".
  assert.equal(foldTitle("x", 0), "x (0)");
  assert.equal(stepsCount(0), "0 steps");
  // The Junctions fold: drawn only when the route has intersections (or Avoid-rated junctions, OWNER-DECISIONS
  // 307, which come from the route's line), and counted by what the list shows.
  assert.match(
    app,
    /const junctions = route\.intersections == null \? \(avoidCount > 0 \? avoidCount : null\) : junctionItems\(route\)\.length \+ avoidCount;/,
  );
  // UI-CLEANUP (the mockup's one-line folds): the count on the right of the line, read in brackets (Fold's count).
  assert.match(app, /\{junctions !== null && \(\s*<Fold title=\{ROUTE_FOLDS\.junctions\.title\} count=\{junctions\}/);
  const at = (text: string) => {
    const i = app.indexOf(text, app.indexOf("function RouteSummary"));
    assert.ok(i > 0, text);
    return i;
  };
  const order = [
    "title={elevationTitle}",
    "title={ROUTE_FOLDS.facilities.title}",
    "<RouteDescription route={route} fold federal={federal} />",
    "<Fold title={ROUTE_FOLDS.junctions.title} count={junctions}",
    "<Fold title={ROUTE_FOLDS.choices.title} count={pickerCount}",
    "title={ROUTE_FOLDS.water.title}",
  ].map(at);
  assert.deepEqual(order, [...order].sort((a, b) => a - b));
  // The route chart (322, 323) sits first, in the elevation slot, and is collapsed on a small screen.
  // UI-CLEANUP (the owner's choice 7): "Elevation and climbs", closed on a computer too; a Mass Ride's keeps its name.
  assert.equal(ROUTE_FOLDS.elevation.title, "Elevation and climbs");
  assert.match(app, /const elevationTitle = profile && chartKind\(route\) === "mass" \? foldName\("mass"\) : ROUTE_FOLDS\.elevation\.title;/);
  assert.equal(chartFoldOpen(false), false);
  assert.equal(chartFoldOpen(true), false);
  assert.ok(app.includes("open={chartFoldOpen(narrow)}"));
  // The climbs list is in it too, so the fold shows for a route with climbs and no usable profile.
  assert.match(app, /\{\(profile \|\| climbs\) && \(\s*<Fold/);
  // Each fold is reached from a heading list: a hidden h3 before it (the a11y review's S5).
  for (const key of ["facilities", "junctions", "choices", "water"] as const) {
    assert.match(app, new RegExp(`heading=\\{ROUTE_FOLDS\\.${key}\\.title\\}\\s+open=\\{ROUTE_FOLDS\\.${key}\\.open\\}`), key);
  }
  assert.match(app, /<h3 className="visually-hidden">\{t\("Totals"\)\}<\/h3>\s*<dl className="stats totals">/);
  // The notices are one line (a count, listed behind it: the owner's choice 5); the figures are folded,
  // the four quick figures first (choice 4).
  assert.match(app, /<FacilityBreakdown route=\{route\} part="notices" \/>/);
  assert.match(app, /<QuickFigures figures=\{quickFigures\(route\)\} \/>[\s\S]{0,1600}<FacilityBreakdown route=\{route\} part="figures" \/>/);
});

test("a Fold: closed unless open, 'Routes to choose from' open by default, and its hidden h3 first", () => {
  // UI-CLEANUP: every fold starts closed (the approved mockup: one line each, no scrolling).
  assert.deepEqual(Object.fromEntries(Object.entries(ROUTE_FOLDS).map(([k, v]) => [k, v.open])), {
    elevation: false,
    facilities: false,
    directions: false,
    junctions: false,
    choices: false,
    water: false,
  });
  const closed = renderToStaticMarkup(createElement(Fold, { title: "Junctions to watch", count: 4, heading: "Junctions to watch", children: "x" }));
  assert.equal(
    closed,
    '<h3 class="visually-hidden">Junctions to watch</h3><details class="fold"><summary><span class="fold-title" aria-hidden="true">Junctions to watch</span><span class="fold-count" aria-hidden="true">4</span><span class="visually-hidden">Junctions to watch (4)</span></summary><div class="fold-body">x</div></details>',
  );
  // A count of 0 is still said; no count, no brackets.
  assert.match(renderToStaticMarkup(createElement(Fold, { title: "x", count: 0, children: "x" })), /<span class="visually-hidden">x \(0\)<\/span>/);
  assert.match(renderToStaticMarkup(createElement(Fold, { title: "x", children: "x" })), /<summary><span class="fold-title">x<\/span><\/summary>/);
  assert.doesNotMatch(renderToStaticMarkup(createElement(Fold, { title: "x", count: null, children: "x" })), /fold-count/);
  const open = renderToStaticMarkup(createElement(Fold, { title: "Bikeshare plan", open: true, children: "x" }));
  assert.match(open, /^<details class="fold" open="">/);
  // An icon is drawn before the title, hidden from the reader.
  assert.match(renderToStaticMarkup(createElement(Fold, { title: "x", icon: "list", children: "x" })), /<summary><svg [^>]*aria-hidden="true"/);
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
      title: ROUTE_FOLDS.directions.title,
      count: stepsCount(2),
      heading: ROUTE_FOLDS.directions.title,
      headingId: "route-description-heading",
      open: false,
      className: "route-description",
      children: createElement("ol", { className: "description-list" }),
    }),
  );
  assert.equal(
    html,
    '<h3 id="route-description-heading" class="visually-hidden">Directions</h3><details class="fold route-description"><summary><span class="fold-title" aria-hidden="true">Directions</span><span class="fold-count" aria-hidden="true">2 steps</span><span class="visually-hidden">Directions (2 steps)</span></summary><div class="fold-body"><ol class="description-list"></ol></div></details>',
  );
  const component = src("../RouteDescription.tsx");
  const fold = component.slice(component.indexOf("if (fold) {"), component.indexOf('<section className="route-description"'));
  assert.match(fold, /if \(entries\.length === 0\) return null;/, "no \"Directions (0 steps)\"");
  assert.match(fold, /<Fold\s+title=\{ROUTE_FOLDS\.directions\.title\}\s+count=\{stepsCount\(steps\.length\)\}\s+icon="list"\s+heading=\{ROUTE_FOLDS\.directions\.title\}\s+headingId="route-description-heading"\s+open=\{open\}/);
  // The rider's open or closed is remembered (writeOpen), once per change.
  assert.match(fold, /onToggle=\{\(now\) => \{\s*if \(now !== open\) \{\s*setOpen\(now\);\s*writeOpen\(now\);/);
  assert.match(fold, /<ol className="description-list">\{items\}<\/ol>/);
});

test("the Points notice is a live region that is always there, empty when there is no notice (395, a11y S2)", () => {
  // Created already holding its text, a live region is often not spoken (VoiceOver with Safari, NVDA with
  // Firefox), so it is rendered empty first and filled later (the mutation re-review's N1).
  // A live region in Plan; in Go's Edit route the app's own region says the notice, so it is not said twice.
  assert.match(app, /<p className=\{notice \? "notice" : "notice notice-empty"\} role=\{noticeLive \? "status" : undefined\}>\s*\{notice \?\? ""\}\s*<\/p>/);
  assert.match(src("../App.tsx"), /notice, noticeLive: mode !== "go",/);
  assert.doesNotMatch(app, /\{notice && \(?\s*<p className="notice"/);
  // The empty one stays in the accessibility tree: no rule takes it out (N3).
  const rules = [...css.matchAll(/([^{}]*\.notice-empty[^{}]*)\{([^}]*)\}/g)];
  assert.ok(rules.length >= 1, "the .notice-empty rule");
  for (const [, selector, declarations] of rules) {
    assert.doesNotMatch(declarations, /display:\s*none|visibility:\s*hidden|content-visibility:\s*hidden/, selector.trim());
  }
});

test("Start, GPX, Link and More are one row under the route's figures (UI-CLEANUP, the owner's choice 8)", () => {
  assert.equal(COPY_LINK, "Copy link");
  // In the route summary, after the stress figure and the alerts; no longer pinned under the panel.
  assert.doesNotMatch(app, /\{\/\* Pinned under/);
  const summary = app.slice(app.indexOf("export function RouteSummary"));
  assert.ok(summary.indexOf("<StressFigure") < summary.indexOf("<RouteActions {...actions} start={start} />"));
  assert.match(app, /<div className="route-actions-row">\s*\{start\}\s*<button type="button" className="secondary icon-button gpx-download" onClick=\{\(\) => downloadRoute\(\)\} aria-label=\{t\("Download GPX"\)\}>/);
  assert.match(app, /<span role="status" className="visually-hidden link-spoken">\s*\{linkSpoken\}/);
  // The spoken confirmation carries the location note (OWNER-DECISIONS 395), and the button is described by it.
  assert.equal(linkSpokenFor(true, ""), COPY_LINK_DONE);
  assert.equal(
    linkSpokenFor(true, "This link includes your location as the start."),
    "Link copied. This link includes your location as the start.",
  );
  assert.equal(linkSpokenFor(false, "This link includes your location as the start."), COPY_LINK_FAILED);
  assert.match(app, /if \(press === linkPresses\.current\) setLinkSpoken\(linkSpokenFor\(done, note\)\);/);
  // "Link" shown, "Copy link" heard: the visible word is in the name (label in name).
  assert.match(app, /onClick=\{copyLink\} aria-label=\{COPY_LINK\} aria-describedby=\{linkNote \? "link-note" : undefined\}>\s*<Icon name="link" \/>\s*<span aria-hidden="true">\{t\("Link"\)\}<\/span>/);
  assert.match(app, /<p id="link-note" className="hint link-note">/);
  // More holds Share and Keep for offline, a disclosure.
  assert.match(app, /className="secondary icon-button route-more" aria-expanded=\{more\} aria-controls=\{moreId\}/);
  // The link is this page and encodePlan's fragment, which never carries the weight (313).
  // v0.9.0, "share the exact route": the link Share makes, naming the exact line shown (lib/sharedRoutes.ts).
  assert.match(app, /const \{ link, kept \} = sharedLinkNow\(\);\s*const done = await copyText\(link, navigator\.clipboard, selectionCopy\);/);
  assert.equal(linkSaidFor(true), COPY_LINK_DONE);
  assert.equal(linkSaidFor(false), COPY_LINK_FAILED);
  assert.match(app, /if \(press === linkPresses\.current\) setLinkSaid\(linkSaidFor\(done\)\);/);
  // Cleared first, so a second press is said again.
  assert.match(app, /const press = \+\+linkPresses\.current;\s*setLinkSaid\(""\);/);
});

test("App writes exactly encodePlan's fragment to the address bar, and a new plan clears 'Link copied.'", () => {
  const writer = app.slice(app.indexOf("// Keep the link in step with the plan"), app.indexOf("}, [points, preset, dials, namesVersion]);"));
  assert.match(writer, /const hash = encodePlan\(points, preset, dials, viaIndices\(points, VIA_MARKS\.isVia\)\);\s*writtenHash\.current = hash;\s*window\.history\.replaceState\(null, "", hash\);/);
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

test("the bottom bar is Plan, Layers, Reports, Save & load and Settings: real buttons, each with words (the owner's choice 6)", () => {
  assert.deepEqual(BAR_ITEMS.map((i) => i.label), ["Plan", "Layers", "Reports", "Save & load", "Settings"]);
  assert.deepEqual(BAR_ITEMS.map((i) => i.opens), ["planner", "layers", "suggest", "gpx", "settings"]);
  assert.equal(BAR_ITEMS[0].id, "plan", "Plan is first (OWNER-DECISIONS 392, 393)");
  assert.ok(BAR_ITEMS.every((i) => i.description.length > 0));
  assert.equal(BAR_ITEMS[4].description, "Opens the settings: My Go (Home, ride type), riding, display and your account.");
  assert.equal(BAR_NAME, "Panel pages", "a landmark name that says what the bar is (the a11y review's N3)");
  assert.match(sidebar, /<nav aria-label=\{BAR_NAME\} className="bottom-bar">/);
  assert.match(sidebar, /<Fragment key=\{item\.id\}>\s*<button\s+id=\{`bar-\$\{item\.id\}`\}\s+type="button"/);
  // The hint is a sibling of the button, not inside it: the name is the label alone, the hint the description once.
  assert.match(sidebar, /<\/button>\s*\{\/\*[\s\S]*?\*\/\}\s*<span id=\{`bar-\$\{item\.id\}-hint`\} hidden>\s*\{item\.description\}\s*<\/span>\s*<\/Fragment>/);
  assert.match(sidebar, /aria-describedby=\{`bar-\$\{item\.id\}-hint`\}/);
  assert.equal(BAR_ITEMS[0].description, "Shows the planner: the points, the ride settings and the route.");
  assert.match(sidebar, /<span>\{item\.label\}<\/span>/);
  // The icon is the shared line icon, hidden from the reader (Icon.tsx: aria-hidden on the svg).
  assert.match(sidebar, /<Icon name=\{ICONS\[item\.id\]\} \/>\s*<span>\{item\.label\}<\/span>/);
  assert.match(src("../Icon.tsx"), /aria-hidden="true"/);
  assert.doesNotMatch(sidebar, /<a /, "no link where a button is meant");
  // Shown in Plan only: Go has its Menu (the mockup's control table).
  assert.match(app, /\{!goMode && <BottomBar view=\{view\} onOpen=\{openSheet\} buttonRef=/);
});

test("a sheet: Back is a labelled button, its heading takes the focus, Escape goes back", () => {
  assert.deepEqual(Object.values(SHEET_TITLES), ["Layers", "Reports", "Review", "Save and load", "Settings", "Nearest", "Find a place to eat", "Ride", "Repair stands and bike shops", "Places to see", "Edit route"]);
  // In visible words, not only an arrow, so the name and the label are one (OWNER-DECISIONS 393).
  assert.equal(BACK_LABEL, "Back to planner");
  assert.doesNotMatch(sidebar, /aria-label="Back to the planner"/);
  // A sheet opened from another sheet goes back to it, and says so (Back to Layers, Back to Menu).
  assert.match(sidebar, /<button type="button" className=\{label === POPUP_CLOSE && modal \? "sheet-back popup-close" : "sheet-back"\} onClick=\{onBack\}>[\s\S]*?<\/svg>\s*\)\}\s*\{label\}\s*<\/button>/, "Back goes back (NIT A)");
  assert.match(sidebar, /backLabel = BACK_LABEL,/);
  // A popup on a phone (the owner, 2026-10-28) says Close where the sheet goes back to the planner or the map.
  assert.match(sidebar, /const label = modal \? popupBackLabel\(backLabel\) : backLabel;/);
  assert.equal(popupBackLabel(BACK_LABEL), "Close");
  assert.equal(popupBackLabel("Close"), "Close");
  assert.equal(popupBackLabel("Back to Menu"), "Back to Menu");
  assert.match(app, /return t\("Back to \{title\}", \{ title: step\.from === "settings" && mode === "go" \? MENU_TITLE : SHEET_TITLES\[step\.from as Exclude<PanelView, "planner">\] \}\);/);
  assert.match(sidebar, /<h2 id=\{`\$\{id\}-title`\} ref=\{headingRef\} tabIndex=\{-1\}>/);
  assert.match(
    sidebar,
    /sheetEscape\(\{ key: event\.key, defaultPrevented: event\.defaultPrevented, target: event\.target as HTMLElement, preventDefault: \(\) => event\.preventDefault\(\) \}, onBack, dialogRef\.current\)/,
  );
  // The error can take the focus (focus() on an element without tabIndex does nothing).
  assert.match(app, /<div ref=\{errorRef\} tabIndex=\{-1\} className=\{`error error-\$\{error\.kind\}`\} role="alert">/);
});

test("where the focus goes on every change of view (mutation SF1)", () => {
  const views: PanelView[] = ["planner", "layers", "suggest", "review", "gpx", "settings", "nearest", "food", "ride"];
  const causes: ViewCause[] = ["bar", "back", "error", "confirm", "planButton", "panelToggle"];
  for (const was of views)
    for (const view of views)
      for (const cause of causes) {
        const got = focusOnViewChange({ was, view, cause });
        const at = `${was}->${view} ${cause}`;
        if (was === view) assert.equal(got, null, at);
        else if (cause === "back") assert.deepEqual(got, { kind: "opener" }, at);
        else if (view !== "planner") assert.deepEqual(got, { kind: "heading", view }, at);
        else if (cause === "error") assert.deepEqual(got, { kind: "error" }, at);
        else if (cause === "confirm") assert.deepEqual(got, { kind: "plan" }, at);
        else if (cause === "planButton") assert.deepEqual(got, { kind: "planner" }, at);
        else if (cause === "panelToggle") assert.equal(got, null, at);
        else assert.deepEqual(got, { kind: "opener" }, at);
      }
  // The way back through nested sheets: Layers then Legend, Back to Layers, Back to the planner.
  const button = { name: "bar-layers" };
  const legendButton = { name: "legend-button" };
  let stack = openOnto([], "planner", button, false);
  assert.deepEqual(stack, [{ from: "planner", opener: button }]);
  stack = openOnto(stack, "layers", legendButton, true);
  let step = backFrom(stack);
  assert.deepEqual([step.view, step.opener], ["layers", legendButton]);
  step = backFrom(step.stack);
  assert.deepEqual([step.view, step.opener], ["planner", button]);
  assert.deepEqual(backFrom(step.stack), { view: "planner", opener: null, stack: [] });
  // A new sheet from the planner, or a sheet not nested, starts the way back again.
  assert.deepEqual(openOnto(stack, "layers", button, false), [{ from: "planner", opener: button }]);
  assert.deepEqual(openOnto(stack, "planner", button, true), [{ from: "planner", opener: button }]);
  assert.match(app, /const openView = \(next: PanelView, opener: HTMLElement \| null, nested = false\) => \{\s*if \(next === "planner"\) \{\s*showPlanner\(\);\s*return;/);
  // From a sheet the view changes and the focus decision does it; on the planner already, the heading is focused and the panel scrolled to the top.
  assert.match(app, /const showPlanner = \(focusHeading = true\) => \{\s*viewCause\.current = focusHeading \? "planButton" : "panelToggle";[\s\S]*?if \(viewNow\.current === "planner"\) \{\s*if \(focusHeading\) \{\s*plannerHeadingRef\.current\?\.focus\(\);\s*panelBodyRef\.current\?\.scrollTo\?\.\(\{ top: 0 \}\);\s*\}\s*\} else setView\("planner"\);/);
  // The phone header's toggle: "Show planner" always shows the planner, even if a sheet was open when it was hidden,
  // and leaves the focus on the toggle (showPlanner(false)); the heading focus is the Plan button's.
  assert.match(app, /\{panelOpen \? t\("Hide planner"\) : t\("Show planner"\)\}/);
  assert.match(app, /if \(panelOpen\) setPanelOpen\(false\);\s*else \{\s*setPanelOpen\(true\);[\s\S]*?showPlanner\(false\);/);
  assert.match(app, /target\.kind === "planner"\) \{[^}]*plannerHeadingRef\.current\?\.focus\(\);/);
  // In Go the heading is out of sight but still the planner's focus target and heading.
  assert.match(app, /<h1 ref=\{plannerHeadingRef\} tabIndex=\{-1\} className=\{goMode \? "visually-hidden" : undefined\}>\s*\{PLANNER_TITLE\}\s*<\/h1>/);
  assert.equal(PLANNER_TITLE, "RouteMaker");
  // App records why: an opener, Back, or the status that brought the planner back.
  assert.match(app, /opened\.current = openOnto\(opened\.current, viewNow\.current, opener, nested\);\s*viewCause\.current = "bar";/);
  assert.match(app, /backTo\.current = step\.opener;\s*viewCause\.current = "back";\s*setView\(step\.view\);/);
  assert.match(app, /viewCause\.current = status\.kind === "confirm" \? "confirm" : "error";\s*setView\("planner"\);/);
  assert.match(app, /focusOnViewChange\(\{ was, view, cause: viewCause\.current \}\)/);
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
  // A popup sheet is a dialog itself: Escape in it is its own, a nested dialog's is still the nested one's.
  const sheet = {};
  const inSheet: Fake = { ...event("Escape"), target: { closest: (s: string) => (s === "dialog" ? sheet : null), getAttribute: () => null } };
  let back = 0;
  assert.equal(sheetEscape(inSheet, () => back++, sheet), true);
  assert.equal(back, 1);
  assert.equal(sheetEscape(event("Escape", { inDialog: true }), () => back++, sheet), false, "a dialog inside the popup");
});

test("the popups (the owner, 2026-10-28): which destinations, and the app's words said inside the open one", () => {
  assert.deepEqual(POPUP_VIEWS, ["settings", "ride", "layers", "gpx", "suggest", "nearest", "food"]);
  for (const id of ["sheet-settings", "sheet-ride", "sheet-layers", "sheet-gpx", "sheet-suggest", "sheet-nearest", "sheet-food"]) {
    const at = app.indexOf(`id="${id}"`);
    assert.ok(at > 0, id);
    assert.match(app.slice(at, app.indexOf(">\n", at) + 1), /\bpopup\b/, `${id} is a popup`);
  }
  for (const id of ["sheet-repair", "sheet-places", "sheet-points"]) {
    const at = app.indexOf(`id="${id}"`);
    assert.doesNotMatch(app.slice(at, app.indexOf(">\n", at) + 1), /\bpopup\b/, `${id} stays a sheet`);
  }
  // A modal on a phone, the panel's side panel on a computer: the one element, so what it holds keeps its state.
  assert.match(sidebar, /const modal = popup && narrow;/);
  assert.match(sidebar, /if \(want === "modal"\) dialog\.showModal\?\.\(\);\s*else if \(want === "panel"\) dialog\.show\?\.\(\);/);
  assert.match(sidebar, /onCancel=\{\(event\) => event\.preventDefault\(\)\}/);
  assert.match(css, /dialog\.popup-sheet:modal \{[^}]*max-height: calc\(100dvh - 8px\);/);
  assert.match(css, /dialog\.popup-sheet:not\(:modal\) \{[^}]*position: static;/);
  const heard: string[] = [];
  const stop = listenForPopupSay((text) => heard.push(text));
  sayInPopup("Link copied.");
  stop();
  sayInPopup("Not heard.");
  assert.deepEqual(heard, ["Link copied."]);
  assert.match(app, /setSaid\(\(s\) => \(\{ text, count: s\.count \+ 1 \}\)\);\s*sayInPopup\(text\);/);
});

test("the Layers sheet holds the switches in the mockup's order, each section with its own key (the owner, 2026-10-19)", () => {
  const sheet = app.slice(app.indexOf('id="sheet-layers"'), app.indexOf('id="sheet-gpx"'));
  // Traffic stress, high-stress lanes, federal land, water, rail stations, then trails and terrain; each a
  // section of one row (lib/layerSection.ts), the layers inside.
  const parts = [
    'switchId="show-stress"',
    "<HighStressLanesSwitch",
    "<FederalLandFor",
    "<WaterSection",
    "<RailStationsSection",
    "<MtbTrailsSwitch",
    "<ClimbsLayerControls",
    "<TopoLinesSwitch",
  ];
  const at = parts.map((part) => sheet.indexOf(part));
  assert.ok(at.every((i) => i > 0), JSON.stringify(at));
  assert.deepEqual(at, [...at].sort((a, b) => a - b));
  // "include the legend within the accordion settings in layers": no Legend sheet or button; the stress key and
  // the junctions' are in the traffic stress section, before the next section.
  assert.ok(!app.includes('id="sheet-legend"') && !app.includes("legend-button") && !app.includes("openLegend"));
  const stress = sheet.slice(sheet.indexOf('switchId="show-stress"'), sheet.indexOf("<FederalLandFor"));
  assert.match(stress, /<StressSectionKey [^\n]*\/>[\s\S]*<JunctionLegend \/>\s*\{\/\*[\s\S]*?\*\/\}\s*\{steepGradesFor\(preset\) && <SteepGradeKey \/>\}\s*\{\/\*[\s\S]*?\*\/\}\s*<RouteHazardKey \/>\s*<\/LayerSection>/);
  assert.match(app, /<StressLegend facilities=\{facilitiesShown\} zoom=\{zoom\} shown=\{stressVisible\} foldedZoom \/>/);
  assert.match(sheet, /\{!federalShown\(preset, true\) && <p className="hint mass-ride-layers">\{MASS_RIDE_LAYERS_NOTE\}<\/p>\}/);
  assert.equal(MASS_RIDE_LAYERS_NOTE, "Mass Ride has its own layers, such as federal land.");
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

test("short or zoomed screens: the whole panel scrolls as one, so nothing pinned crowds out the planner", () => {
  const start = css.indexOf("@media (max-height: 32.5em), (max-width: 22.5em) {");
  assert.ok(start > 0, "the rule is there");
  const rule = css.slice(start, css.indexOf("\n}\n", start));
  assert.match(rule, /\.panel \{\s*overflow-y: auto;/);
  assert.match(rule, /\.panel-body,\s*\.panel-scroll \{\s*flex: none;\s*min-height: auto;\s*overflow: visible;/);
  assert.doesNotMatch(css, /\.panel-scroll[^{]*\{[^}]*\border:/);
  assert.doesNotMatch(css, /\.panel-footer/, "the old footer's rules are gone with it");
  // The scroll to the top reaches whichever scrolls.
  assert.match(app, /panelBodyRef\.current\?\.scrollTo\(\{ top: 0 \}\);\s*panelRef\.current\?\.scrollTo\?\.\(\{ top: 0 \}\);/);
});

test("elsewhere the panel and its body clip, so focusing a sheet's heading cannot scroll the panel itself", () => {
  // A hidden box can still be scrolled; Save & load's visually hidden lines reach below the panel, and focusing
  // its heading scrolled the panel up, its header gone and a band open under the bar (2026-10-27).
  // hidden stays only as the fallback just before clip, for a browser without it.
  assert.match(css, /\n\.panel \{[^}]*overflow: hidden;\s*overflow: clip;/);
  assert.match(css, /\n\.panel-body \{[^}]*overflow: hidden;\s*overflow: clip;/);
  assert.doesNotMatch(css, /\n\.panel(-body)? \{[^}]*overflow: hidden;(?!\s*overflow: clip;)/);
  // And the lines are placed against the part that scrolls, not the panel.
  assert.match(css, /\n\.panel-scroll \{\s*position: relative;/);
});

test("the beta notice is not in the planner any more: it is a chip on the map (lib/betaBanner.ts)", () => {
  const body = app.indexOf('<div id="panel-body"');
  assert.ok(body > 0);
  assert.equal(app.slice(body, app.indexOf('className="panel-scroll"', body)).includes("Beta"), false);
  assert.doesNotMatch(css, /\.beta-banner/);
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
  // Go's bar is before the map and the panel, as it is at the top of the screen (reading order = visual order).
  assert.ok(app.indexOf("<GoTopBar") < app.indexOf("<MapView") && app.indexOf("<MapView") < app.indexOf("<aside"));
  // "No route yet." is read where it stands, and is not in the live region (recheck N-new-2).
  assert.doesNotMatch(app.slice(region, app.indexOf("<aside")), /No route yet/);
  const shownCopy = app.slice(app.indexOf('<div className="status-shown"'));
  assert.doesNotMatch(shownCopy.slice(0, shownCopy.indexOf("</div>")), /No route yet/);
  assert.match(app, /\{status\.kind === "idle" && points\.length < 2 && !goMode && <p className="hint">\{t\("No route yet\."\)\}<\/p>\}/);
  assert.equal((app.match(/aria-live="polite" className="status-line/g) ?? []).length, 1);
  assert.match(app, /\{said\.text\}/);
  assert.match(app, /const said = kindSaid\(next, index, VIA_MARKS\.isVia, loopVias, "added"\);/);
});

test("on a desktop the points come first, then the Ride line, then the route; on a phone the route leads", () => {
  assert.deepEqual(sheetOrder(false, "idle", false), ["points", "presets", "route"]);
  assert.deepEqual(sheetOrder(false, "ok", true), ["points", "presets", "route"]);
  assert.deepEqual(sheetOrder(true, "ok", true), ["route", "points", "presets"]);
  assert.deepEqual(sheetOrder(true, "idle", false), ["points", "presets", "route"]);
});

// ---- OWNER-DECISIONS 384: App's dispatch, the bar's current button, the Settings sheet ----------------

test("App dispatches the focus decision to the right element (the mutation re-check's NIT A)", () => {
  const effect = app.slice(app.indexOf("const target = focusOnViewChange("), app.indexOf("}, [view]);", app.indexOf("const target = focusOnViewChange(")));
  // Back: what opened the sheet, if it is still on screen; else the planner's heading.
  // P3: after a change in Go's Ride sheet, without scrolling to it: Go's sheet goes back to its totals.
  assert.match(effect, /if \(target\.kind === "opener"\) \{\s*const opener = backTo\.current;\s*if \(opener\?\.isConnected && opener\.offsetParent !== null\) opener\.focus\(\{ preventScroll: toTotals \}\);\s*else plannerHeadingRef\.current\?\.focus\(\{ preventScroll: toTotals \}\);\s*if \(toTotals\) scrollPanelToTop\(\);/);
  assert.match(effect, /else if \(target\.kind === "error"\) errorRef\.current\?\.focus\(\);/);
  assert.match(effect, /else if \(target\.kind === "plan"\) planButtonRef\.current\?\.focus\(\);/);
  // A sheet: its heading, by the id SheetFrame gives it.
  assert.match(effect, /const heading = document\.getElementById\(`sheet-\$\{target\.view\}-title`\);\s*heading\?\.focus\(\);/);
  assert.match(sidebar, /<section id=\{id\} className="sheet" aria-labelledby=\{`\$\{id\}-title`\}/);
  assert.match(app, /const openSheet = \(item: BarItem, button: HTMLButtonElement\) => openView\(item\.opens, button\);/);
  assert.match(app, /<BottomBar view=\{view\} onOpen=\{openSheet\}/);
});

test("the bar's current button: the sheet showing, or one opened from it (Suggest's Review)", () => {
  const views: PanelView[] = ["planner", "layers", "suggest", "review", "gpx", "settings", "nearest", "food", "ride"];
  const of: Record<string, PanelView[]> = {
    plan: ["planner"],
    layers: ["layers"],
    suggest: ["suggest", "review"],
    gpx: ["gpx"],
    settings: ["settings"],
  };
  for (const view of views) for (const item of BAR_ITEMS) assert.equal(barCurrent(item, view), of[item.id].includes(view), `${view} ${item.id}`);
  // The map chips' sheets and the Ride sheet are no bar button's.
  for (const view of ["nearest", "food", "ride"] as const) assert.ok(BAR_ITEMS.every((item) => !barCurrent(item, view)), view);
  assert.match(sidebar, /const current = barCurrent\(item, view\);/);
  assert.match(sidebar, /aria-current=\{current \? "true" : undefined\}/);
});

test("the Settings sheet (384): My Go, Riding, Display and Account, most used first (Settings tidy, 2026-10-19); one state, unique ids", () => {
  const sheet = app.slice(app.indexOf('id="sheet-settings"'), app.indexOf("export interface SuggestSheetProps"));
  assert.match(sheet, /title=\{go \? MENU_TITLE : SHEET_TITLES\.settings\}\s+open=\{nav\.view === "settings"\}\s+onBack=\{nav\.back\}\s+backLabel=\{nav\.backLabel\("settings"\)\}\s+popup\s+headingRef=\{settingsHeadingRef\}/);
  // Three tabs (the owner, 2026-10-28: "Settings = display, riding, account"), each a panel that stays in the page.
  assert.match(sheet, /<SettingsTabs tab=\{tab\} onTab=\{setTab\} label=\{go \? MENU_TITLE : SHEET_TITLES\.settings\} \/>/);
  const panels = ["riding", "display", "account"].map((id) => sheet.indexOf(`<div role="tabpanel" id="settings-panel-${id}" aria-labelledby="settings-tab-${id}" className="settings-panel" hidden={tab !== "${id}"}>`));
  assert.ok(panels.every((i) => i > 0), JSON.stringify(panels));
  assert.deepEqual(panels, [...panels].sort((a, b) => a - b));
  const sheets = src("../app/Sheets.tsx");
  assert.match(sheets, /export const SETTINGS_TABS = \["riding", "display", "account"\] as const;/);
  assert.match(sheets, /role="tab"\s+id=\{`settings-tab-\$\{id\}`\}\s+className="settings-tab"\s+aria-selected=\{tab === id\}\s+aria-controls=\{`settings-panel-\$\{id\}`\}\s+tabIndex=\{tab === id \? 0 : -1\}/);
  assert.match(sheets, /event\.key === "ArrowRight"[\s\S]*?event\.key === "ArrowLeft"[\s\S]*?event\.key === "Home"[\s\S]*?event\.key === "End"/);
  // Back from Garmin or Wahoo, on Account, where its line says what happened.
  assert.match(sheets, /useState<SettingsTab>\(\(\) => \(garminReturned \|\| wahooReturned \? "account" : "riding"\)\)/);
  // This device's routes moved to Save and load (the owner, 2026-10-18); the install offer has its own heading.
  assert.doesNotMatch(sheet, /settings-device-heading/);
  const order = ['<MyGoSection controls={myGo} open={nav.view === "settings"} />', ...["settings-ride-heading", "settings-display-heading", "settings-signin-heading"].map((id) => `<h3 id="${id}" className="visually-hidden">`), "<InstallOffer", 'id="settings-about-heading"'].map((at) => sheet.indexOf(at));
  assert.ok(order.every((i) => i > 0), JSON.stringify(order));
  assert.match(app, /<section aria-labelledby="settings-my-go-heading" className="settings-group my-go">\s*<div className="setting-line">\s*<h3 id="settings-my-go-heading">\{t\("My Go"\)\}<\/h3>/);
  assert.deepEqual(order, [...order].sort((a, b) => a - b));
  // Each group keeps its heading for a screen reader's heading list; on screen, its tab names it.
  assert.match(sheet, /<section aria-labelledby="settings-display-heading" className="settings-group">\s*<h3 id="settings-display-heading" className="visually-hidden">\{t\("Display"\)\}<\/h3>/);
  // The sign-in note has its own heading, so heading navigation does not file it under Display.
  assert.match(sheet, /<h3 id="settings-signin-heading" className="visually-hidden">\{t\("Account"\)\}<\/h3>/);
  assert.match(sheet, /<AccessibilitySwitch\s+idBase="settings-contrast"\s+on=\{accessibilityOn\(\)\}\s+source=\{accessibilitySource\(\)\}\s+paletteFromAddress=\{paletteSetByAddress\(\)\}\s+onChange=\{\(on\) => setAccessibility\(on\)\}/);
  assert.ok(sheet.indexOf("Display") < sheet.indexOf("Sign in with Discord"), "the sign-in note is still there, after the display group");
  assert.match(sheet, /onClick=\{\(e\) => isPlainClick\(e\) && rememberPlanForSignIn\(tabSession\(\), window\.location\.hash, linkNote !== ""\)\}/);
  assert.doesNotMatch(app, /sheet-about|aboutHeadingRef|"about"/);
  // Go's Menu: Plan, Suggest, GPX and an admin's Review above the settings, each a button.
  assert.match(sheet, /\{go && \(\s*<nav className="menu-pages" aria-label=\{t\("Pages"\)\}>/);
  // High contrast is only in Settings now (the mockup's Layers has toggles for the map only).
  const layers = app.slice(app.indexOf('id="sheet-layers"'), app.indexOf('id="sheet-gpx"'));
  assert.doesNotMatch(layers, /<AccessibilitySwitch/);
  assert.equal((app.match(/<AccessibilitySwitch/g) ?? []).length, 1);
  const b = renderToStaticMarkup(createElement(AccessibilitySwitch, { idBase: "settings-contrast", on: true, source: "chosen", paletteFromAddress: false, onChange: () => {} }));
  const ids = (html: string) => [...html.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(ids(b), ["settings-contrast-switch", "settings-contrast-label", "settings-contrast-hint"]);
  assert.ok(b.includes('aria-labelledby="settings-contrast-label"') && b.includes('aria-describedby="settings-contrast-hint"'));
  assert.ok(b.includes(">High contrast</span>"));
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

test("Group Ride's stress line: quiet roads and the turns the directions give (the 2026-10-28 audit, P6)", () => {
  const leg = (movement: string | null, kind = "stretch") => ({ kind, from_m: 0, to_m: 1, text: "", turn: movement === null ? null : { movement } }) as never;
  const route = { description: [leg(null), leg("left"), leg("straight"), leg("bear_right"), leg("right"), leg("left", "junction"), leg("uturn")], stress_m: { "1": 950, "2": 0, "4": 50 } } as never;
  assert.equal(turnTotal(route), 4, "left, bear right, right and the U-turn; straight on and a junction's own turn are not counted");
  assert.equal(groupRideLine(route), "Quiet roads · 4 turns");
  assert.equal(groupRideLine({ description: [leg("left")], stress_m: { "1": 80, "3": 20 } } as never), "80% quiet roads · 1 turn");
  const panel = readFileSync(new URL("../app/RoutePanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /const groupLine = preset === "group-ride" \? groupRideLine\(route\) : null;/);
  assert.match(panel, /<StressFigure segments=\{segments\} line=\{groupLine\} go=\{\{ route, peek: go\.peek, onKey: go\.onStressKey \}\} \/>/);
});
