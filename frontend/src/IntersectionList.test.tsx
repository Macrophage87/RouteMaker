import { test } from "node:test";
import assert from "node:assert/strict";
import { click, render } from "./testSupport/render.ts";
import { IntersectionList } from "./IntersectionList.tsx";
import type { JunctionWarning, RouteResponse } from "./lib/api.ts";

// The owner, 2026-11-15: rated junctions are marked on the route and say how stressful they are.

const base: JunctionWarning = {
  m: 1609,
  lon: -77.0,
  lat: 38.9,
  severity: "red",
  reason: "Crossing a 4-lane 40 mph (64 km/h) road, stop sign (rated LTS 4)",
  crossed_tier: 4,
  movement: "straight",
  control: "stop",
  kind: "crossing",
  cost_ft: 4000,
};

const route = (intersections: JunctionWarning[]) => ({ intersections }) as unknown as RouteResponse;

test("a rated junction's row says its level and movement, and opens its card", async () => {
  const chosen: number[] = [];
  const rated: JunctionWarning = { ...base, rated: { move: "cross", level: 4, moves: [{ move: "cross", level: 4, wait_s: 40 }] } };
  const screen = await render(<IntersectionList route={route([base, rated])} onSelect={(i) => chosen.push(i)} />);
  const row = screen.button(/^Rated LTS 4 crossing, At 1\.0 mi/);
  assert.ok(row);
  assert.ok(screen.button(/^Very high stress, At 1\.0 mi/), "the model's junction keeps its words");
  await click(row);
  assert.deepEqual(chosen, [1]);
});

test("a row shows its cost after the reason, and none where there is none to say", async () => {
  const screen = await render(<IntersectionList route={route([{ ...base, calm_mi: 0.45, calm_km: 0.73, time_band: "weekday_rush" }])} onSelect={() => {}} />);
  assert.ok(screen.button(/stop sign \(rated LTS 4\)\. Costs 0\.45 calm mi \(0\.73 calm km\), more at rush hour$/));
  assert.match(screen.text(), /Costs 0\.45 calm mi \(0\.73 calm km\), more at rush hour/);
});
