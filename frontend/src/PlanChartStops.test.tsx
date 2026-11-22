// The route's stops on Plan's chart (Stephen 2026-11-22: "Put the stop icons on the map here"): each stop at its
// distance, its icon where it has one and its number where not, a via point left out. Rendered
// (testSupport/render.ts) on a made-up route; no rider's file.
import { test } from "node:test";
import assert from "node:assert/strict";
import { render } from "./testSupport/render.ts";
import { ElevationChart } from "./ElevationChart.tsx";
import type { RouteProfile, RouteResponse } from "./lib/api.ts";
import type { LonLat } from "./lib/geo.ts";
import { ViaMarks } from "./lib/pointKinds.ts";
import { chartStops } from "./lib/chartStops.ts";
import { NOTE_ICONS } from "./lib/routeNotes.ts";

const LINE: LonLat[] = Array.from({ length: 400 }, (_, i) => [-77.05 + i * 0.000128, 38.9]);
const PROFILE = { interval_m: 100, m: Array.from({ length: 45 }, (_, i) => i * 100), elevation_m: Array(45).fill(10), grade_pct: Array(45).fill(0), climbs: [] } as unknown as RouteProfile;
// Start, a via point (index 1) at 1 km, a stop with a coffee icon (2) at 2 km, a plain stop (3) at 3 km, the end (4).
const POINTS: LonLat[] = [LINE[0], LINE[90], LINE[180], LINE[270], LINE[399]];
const ROUTE = {
  geometry: { type: "LineString", coordinates: LINE },
  distance_m: 4400,
  duration_s: 900,
  stress_spans: [{ from_m: 0, to_m: 4400, tier: 2, facility: null }],
  description: [
    { kind: "stretch", from_m: 0, to_m: 1000, street: "Side Street", tier: 2, text: "Part." },
    { kind: "via", from_m: 1000, to_m: 1000, via: 1, text: "Part." },
    { kind: "stretch", from_m: 1000, to_m: 2000, street: "Side Street", tier: 2, text: "Part." },
    { kind: "via", from_m: 2000, to_m: 2000, via: 2, text: "Part." },
    { kind: "stretch", from_m: 2000, to_m: 3000, street: "Hill Street", tier: 2, text: "Part." },
    { kind: "via", from_m: 3000, to_m: 3000, via: 3, text: "Part." },
    { kind: "stretch", from_m: 3000, to_m: 4400, street: "Hill Street", tier: 2, text: "Part." },
  ],
  profile: PROFILE,
} as unknown as RouteResponse;

function marks(): ViaMarks {
  const m = new ViaMarks();
  m.markAt(POINTS, [1]);
  m.setIcon(POINTS[2], "coffee");
  return m;
}

test("the stops are found at their distances and numbered among themselves; a via point is no stop", () => {
  const m = marks();
  assert.deepEqual(chartStops(ROUTE, POINTS, m.isVia, m.iconOf), [
    { m: 2000, number: 1, icon: "coffee" },
    { m: 3000, number: 2, icon: null },
  ]);
});

test("Plan's chart shows each stop: its icon, or its number where it has none", async () => {
  const m = marks();
  const screen = await render(<ElevationChart route={ROUTE} profile={PROFILE} stops={chartStops(ROUTE, POINTS, m.isVia, m.iconOf)} />);
  const stops = [...screen.container.querySelectorAll(".pc-stop")];
  assert.equal(stops.length, 2);
  // The icon in the rider's style (the Noto picture, or the phone's emoji), never the number.
  assert.ok(stops[0].querySelector("image") || stops[0].textContent === NOTE_ICONS.coffee);
  assert.notEqual(stops[0].textContent, "1");
  assert.equal(stops[1].textContent, "2");
  // In order along the route, the plain stop to the right of the coffee stop.
  const cx = stops.map((s) => Number(s.querySelector("circle")?.getAttribute("cx")));
  assert.ok(cx[0] < cx[1]);
});

test("Go's small chart and a chart given no stops draw none", async () => {
  const m = marks();
  const go = await render(<ElevationChart route={ROUTE} profile={PROFILE} stops={chartStops(ROUTE, POINTS, m.isVia, m.iconOf)} compact />);
  assert.equal(go.container.querySelectorAll(".pc-stop").length, 0);
  const none = await render(<ElevationChart route={ROUTE} profile={PROFILE} />);
  assert.equal(none.container.querySelectorAll(".pc-stop").length, 0);
});
