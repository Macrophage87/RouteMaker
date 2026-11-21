import { test } from "node:test";
import assert from "node:assert/strict";
import "./testSupport/render.ts";
import { junctionCardBody } from "./lib/junctionCard.ts";
import { junctionItems } from "./lib/intersectionMarkers.ts";
import type { JunctionWarning } from "./lib/api.ts";

// What a rider reads on a junction's card (OWNER-DECISIONS 172, 467; the owner, 2026-11-15:
// "The junction should be clickable" and "should tell us how stressful the junction is").

const base: JunctionWarning = {
  m: 1609,
  lon: -77.0,
  lat: 38.9,
  severity: "red",
  reason: "Crossing a 4-lane 40 mph (64 km/h) road, stop sign",
  crossed_tier: 4,
  movement: "straight",
  control: "stop",
  kind: "crossing",
  cost_ft: 4000,
  calm_mi: 0.76,
  calm_km: 1.22,
};

const lines = (junction: JunctionWarning, more: Record<string, unknown> = {}) => {
  const [item] = junctionItems({ intersections: [junction], ...more });
  return [...junctionCardBody(item).children].flatMap((child) => (child.tagName === "UL" ? [...child.children] : [child])).map((el) => el.textContent);
};

test("a junction's card says what it is, why, its cost and how to plan around it", () => {
  assert.deepEqual(lines(base), [
    "Very high stress",
    "Crossing a 4-lane 40 mph (64 km/h) road, stop sign",
    "Costs 0.76 calm mi (1.22 calm km).",
    "At 1.0 mi (1.6 km). Drag the route away to plan around it.",
  ]);
});

test("a rated junction's card lists each movement that can be made, this route's marked", () => {
  const rated: JunctionWarning = {
    ...base,
    rated: {
      move: "cross",
      level: 4,
      moves: [
        { move: "cross", level: 4, wait_s: 41 },
        { move: "along", level: 1.5, wait_s: null },
      ],
    },
  };
  assert.deepEqual(lines(rated), [
    "Rated LTS 4 crossing",
    "Crossing a 4-lane 40 mph (64 km/h) road, stop sign",
    "Crossing: LTS 4, about 40 s (this route)",
    "Riding along: LTS 1.5",
    "Costs 0.76 calm mi (1.22 calm km).",
    "At 1.0 mi (1.6 km). Drag the route away to plan around it.",
  ]);
});

test("a Mass Ride's junction with nothing to say about corkers has no cost line", () => {
  assert.deepEqual(lines(base, { preset: "mass-ride" }), [
    "Very high stress",
    "Crossing a 4-lane 40 mph (64 km/h) road, stop sign",
    "At 1.0 mi (1.6 km). Drag the route away to plan around it.",
  ]);
});
