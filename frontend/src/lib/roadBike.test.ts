import assert from "node:assert/strict";
import test from "node:test";
import { ROAD_BIKE_NO_PAVED_MAP, roadBikeNote } from "./roadBike.ts";

test("a Road Bike route the standard map answered says the paved-only map is not available", () => {
  assert.equal(roadBikeNote({ preset: "road-bike", variant: "standard" }), ROAD_BIKE_NO_PAVED_MAP);
});

test("on its own map, with Keep to roads, or on another ride type, nothing is said", () => {
  assert.equal(roadBikeNote({ preset: "road-bike", variant: "paved" }), null);
  assert.equal(roadBikeNote({ preset: "road-bike", variant: "no-trail" }), null);
  assert.equal(roadBikeNote({ preset: "default", variant: "standard" }), null);
  assert.equal(roadBikeNote(null), null);
});
