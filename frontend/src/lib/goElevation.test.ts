// The elevation chart in Go (Stephen 2026-10-13) and its labels at phone width.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { CHART_TYPE } from "./profileChart.ts";

const src = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");
const panel = src("../app/RoutePanel.tsx");
const chart = src("../ElevationChart.tsx");

test("Go's route sheet shows the compact chart above Info, bigger than peek and not for a Mass Ride", () => {
  const go = panel.slice(panel.indexOf("if (goMode) {"));
  const line = '{!go.peek && profile && chartKind(route) !== "mass" && <ElevationChart route={route} profile={profile} onScrub={onScrub} compact />}';
  assert.ok(go.includes(line));
  assert.ok(go.indexOf(line) < go.indexOf("{!go.peek && infoBody}"), "the chart leads, the details follow");
});

test("the compact chart keeps the slider and its words for a screen reader, and leaves the key and tables to Plan", () => {
  assert.match(chart, /className=\{compact \? "pc-summary visually-hidden" : "pc-summary"\}/);
  assert.match(chart, /aria-describedby=\{compact \? `\$\{uid\}-summary \$\{uid\}-keys` : `\$\{uid\}-keys`\}/);
  const hidden = chart.slice(chart.indexOf("{!compact && ("));
  for (const part of ['className="pc-legend"', 'className="hint pc-source"', 'className="pc-table-fold"']) {
    assert.ok(hidden.indexOf(part) > 0 && hidden.indexOf(part) < hidden.indexOf("        </>\n      )}"), part);
  }
});

test("the rolling stress title clears the elevation's bottom label", () => {
  const m = chart.match(/calm: \{ height: (\d+), elevTop: \d+, elevBottom: (\d+), markerY: (\d+),/);
  assert.ok(m);
  const [, , elevBottom, markerY] = m.map(Number);
  // The bottom label's second line sits on elevBottom; the title's first line on markerY - 6, CHART_TYPE tall.
  assert.ok(markerY - 6 - CHART_TYPE >= elevBottom + 4, "at least 4 units between the two");
});
