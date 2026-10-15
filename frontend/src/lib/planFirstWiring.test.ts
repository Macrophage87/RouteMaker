/** Plan mode's plan-first wiring (v0.7.0): App.tsx and app/PlanPanel.tsx, read as source. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const app = read("../App.tsx");
const panel = read("../app/PlanPanel.tsx");

test("Plan routes on its Route button; Go routes at once; a link, a file or Undo after Clear opens drawn", () => {
  assert.match(app, /const planFirst = mode === "plan" && !riding;/);
  assert.match(app, /const \[routeAsk, setRouteAsk\] = useState\(initialPlan\.points\.length >= 2 \? 1 : 0\);/);
  assert.match(app, /if \(planFirst && !pressed && !samePlan && !backToDrawn\) return;/);
  assert.match(app, /\}, \[points, preset, planDials, confirmedKm, routeAsk, planFirst\]\);/);
  // A link and an opened file are routed as they open.
  assert.ok((app.match(/forgetDrawn\(\);\s*setRouteAsk\(\(n\) => n \+ 1\);/g) ?? []).length >= 2);
  // The Route button says "Planning route", and Cancel stops the request and keeps the plan.
  assert.match(app, /const pressRoute = \(\) => \{\s*setRouteAsk\(\(n\) => n \+ 1\);\s*announce\(PLANNING_SAID\);/);
  assert.match(app, /const cancelRouting = \(\) => \{\s*scheduler\.current\?\.clear\(\);/);
});

test("a changed plan greys the line and keeps a dashed ghost of the old one with a summary after an update", () => {
  assert.match(app, /const planEdited = planFirst && planChanged\(drawn, points, preset, routeKey\);/);
  assert.match(app, /stale=\{riding \? false : stale \|\| planEdited\}/);
  assert.match(app, /ghost=\{riding \? null : ghost\}/);
  assert.match(app, /if \(plan\.pressed && before\) \{\s*setGhost\(before\.route\.geometry\.coordinates\);\s*setChangeLine\(changeSummary\(before\.route, result\.route\)\);/);
  const map = read("../MapView.tsx");
  assert.match(map, /"line-dasharray": \[2, 1\.5\]/);
});

test("Reset goes back to the drawn plan without routing, Clear keeps the ride, and both are undoable edits", () => {
  assert.match(app, /commit\(back\.points as LonLat\[\], back\.ride\);/);
  assert.match(app, /resetUnavailable=\{planEdited \? null : RESET_NOTHING\}/);
  assert.match(app, /const clearPlan = \(\) => \{\s*setGhost\(null\);\s*setChangeLine\(null\);\s*clearAll\(\);/);
  // Reset is aria-disabled with its reason, never removed or disabled outright.
  assert.match(panel, /aria-disabled=\{resetUnavailable \? true : undefined\}/);
  assert.match(panel, /aria-describedby=\{resetUnavailable \? resetWhy : undefined\}/);
});

test("the panel: sentences of links, Route with Enter or Ctrl+Enter, progress with its step, seconds and Cancel", () => {
  assert.match(panel, /className="link plan-phrase" onClick=\{\(\) => onPhrase\(phrase\.target as PhraseTarget\)\}/);
  assert.match(panel, /aria-keyshortcuts="Control\+Enter Meta\+Enter"/);
  assert.match(panel, /if \(!\(event\.ctrlKey \|\| event\.metaKey\) && event\.target !== event\.currentTarget\) return;/);
  assert.match(panel, /<progress className="planning" aria-label=\{`Planning route: \$\{routing\.step\}`\} \/>/);
  assert.match(panel, /Cancel/);
  // It leads Plan's sheet.
  assert.match(app, /\{planPanel\}\s*\{order\.map\(\(id\) => sections\[id\]\)\}/);
});
