// The elevation chart in Go (Stephen 2026-10-13) and its labels at phone width.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { CHART_TYPE } from "./profileChart.ts";

const src = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");
const panel = src("../app/RoutePanel.tsx");
const chart = src("../ElevationChart.tsx");

test("Go's route sheet shows the compact chart under Start, at the full sheet only and not for a Mass Ride", () => {
  const go = panel.slice(panel.indexOf("if (goMode) {"));
  // Review F8: full sheet only (or a wide page, which has no sheet), so the half sheet is about one screen.
  const line = '{go.full && profile && chartKind(route) !== "mass" && <ElevationChart route={trip} profile={profile} onScrub={onScrub} compact />}';
  assert.match(src("../App.tsx"), /full: goSheet === "full" \|\| \(!narrow && goSheet !== "peek"\),/);
  assert.ok(go.includes(line));
  assert.ok(go.indexOf(line) > go.indexOf('className="go-chips"'), "Start and the route's options are never pushed down by the chart");
  // The elevation alone in Go: no rolling stress or strip, so it stays short.
  assert.match(chart, /const calm = useMemo\(\(\) => \(compact \? null : usableCalm\(profile\)\), \[compact, profile\]\);/);
  assert.match(chart, /\{!calm && !compact && \(/);
});

test("the compact chart keeps the slider and its words for a screen reader, and leaves the key and tables to Plan", () => {
  // The summary and the keys are said, out of sight, in Plan too (Plan streamline, 2026-10-17).
  assert.match(chart, /className="pc-summary visually-hidden"/);
  assert.match(chart, /className="visually-hidden pc-keys"/);
  assert.match(chart, /aria-describedby=\{`\$\{uid\}-summary \$\{uid\}-keys`\}/);
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
