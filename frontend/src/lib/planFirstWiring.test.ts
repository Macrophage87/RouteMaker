/** Plan mode's plan-first wiring (v0.7.0): App.tsx and app/PlanPanel.tsx, read as source. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { CLEARED_SAID, GO_CLEARED_SAID, ROUTE_UP_TO_DATE, planRowShown } from "./planFirst.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const app = read("../App.tsx");
const panel = read("../app/PlanPanel.tsx");

test("Plan routes on its Route button; Go routes at once; a link, a file or Undo after Clear opens drawn", () => {
  assert.match(app, /const planFirst = mode === "plan" && !riding;/);
  assert.match(app, /const \[routeAsk, setRouteAsk\] = useState\(initialPlan\.points\.length >= 2 \? 1 : 0\);/);
  assert.match(app, /if \(planFirst && !pressed && !backToDrawn\) return;/);
  assert.match(app, /\}, \[points, preset, planDials, confirmedKm, routeAsk, planFirst\]\);/);
  // A link and an opened file are routed as they open.
  assert.ok((app.match(/forgetDrawn\(\);\s*setRouteAsk\(\(n\) => n \+ 1\);/g) ?? []).length >= 2);
  // The Route button says "Planning route", and Cancel stops the request and keeps the plan.
  assert.match(app, /const pressRoute = \(\) => \{\s*sendNow\.current = true;\s*setRouteAsk\(\(n\) => n \+ 1\);\s*announce\(PLANNING_SAID\);/);
  assert.match(app, /const cancelRouting = \(\) => \{\s*scheduler\.current\?\.clear\(\);/);
});

test("a changed plan greys the line and keeps a dashed ghost of the old one with a summary after an update", () => {
  assert.match(app, /const planEdited = planFirst && planChanged\(drawn, points, preset, planKey\);/);
  assert.match(app, /stale=\{riding \? false : stale \|\| planEdited\}/);
  // v0.8.2: with no ghost, the standard way through a closure the route goes round takes its place.
  assert.match(app, /ghost=\{riding \? \(rideView\?\.other \?\? null\) : reviewing \? null : \(ghost \?\? shown\?\.closure_through\?\.geometry\.coordinates \?\? null\)\}/);
  assert.match(app, /if \(plan\.pressed && before\) \{\s*setGhost\(before\.route\.geometry\.coordinates\);\s*setChangeLine\(changeSummary\(before\.route, result\.route\)\);/);
  // The per-leg details behind the summary.
  assert.match(app, /setChangeDetails\(legChanges\(before, drawnNow, VIA_MARKS\.isVia, \(p\) => namer\.name\(p\)\?\.name\)\);/);
  const map = read("../MapView.tsx");
  assert.match(map, /"line-dasharray": \[2, 1\.5\]/);
});

test("Reset goes back to the drawn plan without routing, Clear keeps the ride, and both are undoable edits", () => {
  assert.match(app, /commit\(back\.points as LonLat\[\], back\.ride\);/);
  assert.match(app, /resetUnavailable=\{planEdited \? null : RESET_NOTHING\}/);
  assert.match(app, /const clearPlan = \(\) => \{\s*setGhost\(null\);\s*setChangeLine\(null\);\s*setChangeDetails\(\[\]\);\s*clearAll\(\);/);
  // Reset puts back the stations and the transit option the drawn plan was routed with.
  assert.match(app, /setStationPins\(back\.pins\);\s*setTransitPick\(back\.transitPick\);/);
  // Reset is aria-disabled with its reason, never removed or disabled outright.
  assert.match(panel, /aria-disabled=\{resetUnavailable \? true : undefined\}/);
  assert.match(panel, /aria-describedby=\{resetUnavailable \? resetWhy : undefined\}/);
});

test("Clear says so and hands the focus to the place search; Plan's Clear stays focusable (review a11y-1)", () => {
  assert.equal(CLEARED_SAID, "Plan cleared. Undo brings it back.");
  // Go names the route, as its Clear button does.
  assert.equal(GO_CLEARED_SAID, "Route cleared. Undo brings it back.");
  assert.match(app, /commit\(\[\], ride\.imported \|\| startDials !== ride\.dials \? \{ \.\.\.ride, imported: null, dials: startDials \} : undefined\);\s*\/\/[^\n]*\n\s*announce\(modeRef\.current === "go" \? GO_CLEARED_SAID : CLEARED_SAID\);\s*focusAfterRemove\.current = -1;/);
  // -1: no Remove button, the search; Go's Where to? waits for the cleared route to stop hiding it.
  assert.match(app, /const target = index < 0 \? null : removeRefs\.current/);
  assert.match(app, /panelRef\.current\?\.querySelector\("\.go-search"\)/);
  assert.match(app, /if \(!target && index < 0 && route && input\?\.closest\("\[hidden\]"\)\) return;/);
  // One Clear in Plan (P10): the bar's trash, while there is a point; the panel keeps Reset only.
  assert.match(app, /\{points\.length > 0 && \(\s*<button type="button" className="secondary plan-bar-small" onClick=\{clearPlan\} aria-label=\{t\("Clear the plan"\)\}/);
  assert.doesNotMatch(panel, /onClear|CLEAR_LABEL/);
  // Not left for a later edit when the route does not go.
  assert.match(app, /if \(focusAfterRemove\.current === -1\) focusAfterRemove\.current = null;\s*\}, CLEAR_FOCUS_WAIT_MS\);/);
});

test("in Plan a station or a transit option is an edit like any other: it marks the plan changed and waits for Route", () => {
  // Both are part of planDials, so of planKey, which the drawn plan is compared by (all but Go's closuresNow).
  assert.match(app, /const \{ closuresNow: _now, \.\.\.keyed \} = planDials;\s*return JSON\.stringify\(keyed\);/);
  assert.match(app, /pins: stationPins, transitPick \}/);
  // No exception lets them route at once: only the Route button, or going back to the drawn plan.
  assert.doesNotMatch(app, /if \(planFirst && !pressed[^\n]*samePlan/);
  assert.match(app, /const backToDrawn = answer === null && drawnRef\.current !== null && !planChanged\(drawnRef\.current, points, preset, planKey\);/);
  assert.match(app, /dialsKey: planKey,\s*pressed: pressed && planFirst,\s*pins: stationPins,\s*transitPick,/);
});

test("the change line's Details opens the per-leg changes, a disclosure for the keyboard and screen readers", () => {
  assert.match(panel, /aria-expanded=\{detailsOpen\} aria-controls=\{detailsId\} onClick=\{\(\) => setDetailsOpen\(!detailsOpen\)\}/);
  assert.match(panel, /\{t\("Details"\)\}<span className="visually-hidden">\{" "\}\{t\("by leg"\)\}<\/span>/);
  assert.match(panel, /<ul id=\{detailsId\} className="plan-change-details" hidden=\{!detailsOpen\}>/);
  assert.match(app, /details=\{changeDetails\}/);
});

test("the panel: the plan in words as its description, Route with Enter or Ctrl+Enter, progress with its step, seconds and Cancel", () => {
  // Plan streamline (2026-10-17): the sentences are out of sight, the panel's description; the points and the ride
  // chips show the plan.
  assert.match(panel, /<p id=\{planId\} className="visually-hidden plan-sentences">/);
  // Why Route is unavailable, out of sight, is part of the description; Enter then says it on the page's status line.
  assert.match(panel, /aria-describedby=\{whySaid \? `\$\{planId\} \$\{routeWhy\}` : planId\}/);
  assert.match(panel, /if \(button\.unavailable === null\) onRoute\(\);\s*else onSay\?\.\(button\.unavailable\);/);
  assert.match(app, /onSay=\{announce\}/);
  // One Route (P10): Plan's bar's; the panel has no Route button, and a route up to date shows no row, said out of sight.
  assert.doesNotMatch(panel, /✓ up to date|More: Reset and Clear|aria-keyshortcuts="Control\+Enter Meta\+Enter"\s*onFocus/);
  assert.match(panel, /\{button\.unavailable && !locate && !routing && \(\s*<p id=\{routeWhy\} className="visually-hidden plan-route-state">\s*\{button\.unavailable\}/);
  assert.equal(planRowShown({ routing: false, locate: false, unavailable: ROUTE_UP_TO_DATE }), false);
  assert.equal(planRowShown({ routing: false, locate: false, unavailable: null }), true);
  assert.equal(planRowShown({ routing: true, locate: false, unavailable: ROUTE_UP_TO_DATE }), true);
  assert.equal(planRowShown({ routing: false, locate: true, unavailable: null }), true);
  assert.match(panel, /className="secondary plan-reset"/);
  assert.match(panel, /aria-keyshortcuts="Control\+Enter Meta\+Enter"/);
  assert.match(panel, /if \(!\(event\.ctrlKey \|\| event\.metaKey\) && event\.target !== event\.currentTarget\) return;/);
  assert.match(panel, /<progress className="planning" aria-label=\{t\("Planning route: \{step\}", \{ step: routing\.step \}\)\} \/>/);
  assert.match(panel, /Cancel/);
  // It follows the points and the ride, above the route; on a phone with a route, where the route comes first, on top.
  assert.match(app, /\{\(order\[0\] === "route" \? \[planPanel, \.\.\.order\.map\(\(id\) => sections\[id\]\)\] : order\.flatMap\(\(id\) => \(id === "route" \? \[planPanel, sections\[id\]\] : \[sections\[id\]\]\)\)\)\}/);
});
