// The ride map's other labels, larger in a ride by the street names' share (the accessibility review, 2026-10-29).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { MTB_LABEL, MTB_LABEL_LAYER_ID } from "../stressStyle.js";
import { RIDE_LABEL_SCALE, RIDE_SCALED_LABEL_LAYERS, scaledTextSize } from "./rideLabelSize.ts";
import { STEEP_GRADE_LAYER, steepGradeLayer } from "./steepGrades.ts";
import { MILES_LABEL_LAYER, milesLabelLayer } from "./trailMiles.ts";
import { CLIMBS_MARKER_LAYER, climbMarkerLayer } from "./climbs.ts";

const sizeOf = (layer: Record<string, unknown>) => (layer.layout as Record<string, unknown>)["text-size"];

test("grades, mile markers, mountain-bike names and climbs go up by the street names' share (20 / 15)", () => {
  assert.equal(RIDE_LABEL_SCALE, 20 / 15);
  assert.deepEqual([...RIDE_SCALED_LABEL_LAYERS].sort(), [STEEP_GRADE_LAYER, MILES_LABEL_LAYER, MTB_LABEL_LAYER_ID, CLIMBS_MARKER_LAYER].sort());
  assert.equal(scaledTextSize(sizeOf(steepGradeLayer()), RIDE_LABEL_SCALE), 17);
  assert.equal(scaledTextSize(sizeOf(milesLabelLayer()), RIDE_LABEL_SCALE), 17);
  assert.equal(scaledTextSize(MTB_LABEL.size, RIDE_LABEL_SCALE), 20);
  // A zoom curve keeps its stops; only its sizes go up.
  const climb = sizeOf(climbMarkerLayer()) as unknown[];
  assert.deepEqual(scaledTextSize(climb, RIDE_LABEL_SCALE), [...climb.slice(0, 4), 12, climb[5], 15]);
  assert.deepEqual(scaledTextSize(["step", ["zoom"], 10, 14, 13], 2), ["step", ["zoom"], 20, 14, 26]);
  assert.deepEqual(scaledTextSize(["get", "size"], 2), ["get", "size"], "anything else is left as it is");
});

test("the map sets them in a ride and puts each back after, as layers come and go", () => {
  const map = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(map, /baseLabelSize\.current\[id\] \?\?= map\.getLayoutProperty\(id, "text-size"\);/);
  assert.match(map, /const want = riding \? scaledTextSize\(base, RIDE_LABEL_SCALE\) : base;/);
});
