import assert from "node:assert/strict";
import test from "node:test";
import {
  ROAD_BIKE_NO_PAVED_MAP,
  ROAD_BIKE_NO_PAVED_MAP_SHORT,
  ROAD_BIKE_NO_WEEKEND_MAP,
  ROAD_BIKE_NO_WEEKEND_MAP_SHORT,
  roadBikeNote,
  roadBikeNotice,
} from "./roadBike.ts";

test("a Road Bike route the standard map answered says the paved-only map is not available", () => {
  assert.equal(roadBikeNote({ preset: "road-bike", variant: "standard" }), ROAD_BIKE_NO_PAVED_MAP);
  assert.equal(roadBikeNote({ preset: "road-bike", variant: "standard", dials: { when: "weekend" } }), ROAD_BIKE_NO_PAVED_MAP);
});

test("on its own map, with Keep to roads, or on another ride type, nothing is said", () => {
  assert.equal(roadBikeNote({ preset: "road-bike", variant: "paved" }), null);
  assert.equal(roadBikeNote({ preset: "road-bike", variant: "paved", dials: { when: "weekday_rush" } }), null);
  assert.equal(roadBikeNote({ preset: "road-bike", variant: "paved-weekend", dials: { when: "weekend" } }), null);
  assert.equal(roadBikeNote({ preset: "road-bike", variant: "no-trail" }), null);
  assert.equal(roadBikeNote({ preset: "default", variant: "standard" }), null);
  assert.equal(roadBikeNote(null), null);
});

test("a weekend Road Bike route the paved-only map answered says the weekend map is not available", () => {
  // The weekend twin (Variant.PAVED_WEEKEND) falls back to the paved-only map (core/routing.py, twin_fallback).
  const fellBack = { preset: "road-bike", variant: "paved", dials: { when: "weekend" } } as const;
  assert.equal(roadBikeNote(fellBack), ROAD_BIKE_NO_WEEKEND_MAP);
  assert.deepEqual(roadBikeNotice(fellBack), { text: ROAD_BIKE_NO_WEEKEND_MAP, short: ROAD_BIKE_NO_WEEKEND_MAP_SHORT });
  assert.match(ROAD_BIKE_NO_WEEKEND_MAP, /Beach Drive/);
});

test("the short lines fit Plan's one-line notes and still name what is lost", () => {
  assert.ok(ROAD_BIKE_NO_PAVED_MAP_SHORT.length <= 45);
  assert.match(ROAD_BIKE_NO_PAVED_MAP_SHORT, /gravel/);
  assert.ok(ROAD_BIKE_NO_WEEKEND_MAP_SHORT.length <= 45);
  assert.match(ROAD_BIKE_NO_WEEKEND_MAP_SHORT, /parkways/);
});
