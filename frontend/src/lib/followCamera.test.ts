import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { bearingGap, followMoveNeeded, mapPixelRatio, type FollowMove } from "./followCamera.ts";

const AT_REST: FollowMove = {
  riderPx: [200, 400],
  targetPx: [200, 400],
  bearingNow: 90,
  bearingWant: 90,
  zoomNow: 16,
  zoomWant: 16,
  first: false,
  unsettled: false,
};

test("a rider stood still, the camera already on them, makes no camera move", () => {
  assert.equal(followMoveNeeded(AT_REST), false);
  assert.equal(followMoveNeeded({ ...AT_REST, riderPx: [201.5, 401.5], bearingWant: 92 }), false);
});

test("a rider moved 3 px or more on screen moves the camera", () => {
  assert.equal(followMoveNeeded({ ...AT_REST, riderPx: [203, 400] }), true);
  assert.equal(followMoveNeeded({ ...AT_REST, riderPx: [200, 396] }), true);
});

test("a heading turned 3 degrees or more moves the camera, across north too", () => {
  assert.equal(followMoveNeeded({ ...AT_REST, bearingWant: 93 }), true);
  assert.equal(followMoveNeeded({ ...AT_REST, bearingNow: 359, bearingWant: 1 }), false);
  assert.equal(followMoveNeeded({ ...AT_REST, bearingNow: 358, bearingWant: 2 }), true);
  assert.equal(bearingGap(-179, 179), 2);
});

test("a new zoom, the first fix followed, a reset or an unsettled map always moves the camera", () => {
  assert.equal(followMoveNeeded({ ...AT_REST, zoomWant: 16.5 }), true);
  assert.equal(followMoveNeeded({ ...AT_REST, first: true }), true);
  assert.equal(followMoveNeeded({ ...AT_REST, unsettled: true }), true);
});

test("a ride or Roam draws the map at a pixel ratio of at most 2; off the bike at the screen's own", () => {
  assert.equal(mapPixelRatio(3, true), 2);
  assert.equal(mapPixelRatio(1.5, true), 1.5);
  assert.equal(mapPixelRatio(3, false), 3);
  assert.equal(mapPixelRatio(Number.NaN, true), 1);
});

const mapView = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");

test("the follow camera skips a move that would not show, and the rider's marker still moves (battery audit)", () => {
  assert.match(mapView, /riderMarker\.current\.setLngLat\(rider\.point\);/);
  assert.match(mapView, /if \(\s*!followMoveNeeded\(\{[\s\S]*?first: first \|\| reset,[\s\S]*?\)\s*\) \{\s*return;\s*\}\s*map\.easeTo\(\{ center: rider\.point/);
});

test("the main map shows new labels without a fade, as the share card's does (battery audit)", () => {
  assert.match(mapView, /new maplibregl\.Map\(\{[\s\S]*?fadeDuration: 0,[\s\S]*?\}\);/);
});

test("the map's bearing is set on the compass alone, not the document's root, at each turn and fix (battery audit)", () => {
  assert.doesNotMatch(mapView, /documentElement\.style\.setProperty\("--map-bearing"/);
  assert.match(mapView, /querySelectorAll<HTMLElement>\("\.ride-compass"\)/);
  assert.match(mapView, /const bearingVar = \(\) => showBearing\(map\);/);
});

test("a ride or Roam sets the map's pixel ratio, and its end gives the screen's back (battery audit)", () => {
  assert.match(mapView, /map\.setPixelRatio\(mapPixelRatio\(window\.devicePixelRatio, onBike\)\)/);
});
