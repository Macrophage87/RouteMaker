// Plan on a wide screen and the route's folds (Stephen 2026-10-21: "Plan is now a massive scrolling mess again ...
// Especially on a wider screen there's a lot of room"; "the left panel has all of the parameters to adjust, and the
// right would have the outputs"): placement only, so the reading and Tab order stay the DOM's, and the route
// summary's folds open one at a time.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ROUTE_FOLD_GROUP } from "./sidebar.ts";
import { Fold } from "./sidebarParts.ts";

const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("from 1200 px wide, with a route, the route is its own card on the map's right; the planner keeps the rest", () => {
  const wide = css.slice(css.indexOf("@media (min-width: 1200px) {\n  .app:not(.go-mode):has(.panel.open .planner-view"));
  assert.ok(wide.length > 0, "the wide rule");
  const rule = wide.slice(0, wide.indexOf("\n}\n"));
  assert.match(rule, /> \.route-section:has\(\.summary\) \{\s*position: fixed;\s*top: 12px;\s*right: 12px;\s*width: var\(--panel-w\);/);
  assert.match(rule, /overflow-y: auto;/);
  // The map's right-hand controls step left of the card.
  assert.match(rule, /\.maplibregl-ctrl-top-right,\s*\.app:not\(\.go-mode\) \.maplibregl-ctrl-bottom-right \{\s*right: var\(--out-w, 0px\);/);
  // Placement only: nothing reorders what is read.
  assert.doesNotMatch(rule, /\border:|flex-direction: column-reverse/);
  // A framed route stays clear of the card.
  assert.match(read("../App.tsx"), /getComputedStyle\(out\)\.position === "fixed"/);
});

test("the panel's width is one variable, and what sits right of the planner follows it", () => {
  assert.match(css, /--panel-w: 400px;/);
  assert.match(css, /\.panel \{[^}]*width: var\(--panel-w\);/);
  assert.doesNotMatch(css, /left: 424px;/);
  // The credits and the trail key move with the right-hand controls, clear of the route card.
  assert.match(css, /max-width: calc\(100vw - 510px - var\(--out-w, 0px\)\);/);
  assert.match(css, /\.mtb-map-key \{\s*right: calc\(10px \+ var\(--out-w, 0px\)\);/);
  assert.match(css, /\.plan-map-bar \{[^}]*right: calc\(60px \+ var\(--out-w, 0px\)\);/);
});

test("the route summary's folds share one name, so one is open at a time", () => {
  const html = renderToStaticMarkup(h(Fold, { title: "Stress and facilities", name: ROUTE_FOLD_GROUP }, "body"));
  assert.match(html, /<details class="fold" name="route-folds">/);
  const panel = read("../app/RoutePanel.tsx");
  // Every fold of the route summary, from the chart's to the end of the panel, is in the group.
  const summary = panel.slice(panel.lastIndexOf("<Fold", panel.indexOf('className="elevation-fold"')));
  const folds = summary.split("<Fold").slice(1);
  assert.equal(folds.length, 6, "elevation, capacity, facilities, junctions, choices, water");
  for (const fold of folds) assert.match(fold.slice(0, fold.indexOf(">\n")), /name=\{ROUTE_FOLD_GROUP\}/);
  assert.match(read("../RouteDescription.tsx"), /className="route-description"\s*name=\{ROUTE_FOLD_GROUP\}/);
  // Folds outside the summary (bikeshare and transit plans, the ride sheet) keep their own open state.
  assert.doesNotMatch(panel, /bikeshare-fold"[^>]*name=/);
});
