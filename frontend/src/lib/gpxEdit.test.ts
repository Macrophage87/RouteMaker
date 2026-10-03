import { test } from "node:test";
import assert from "node:assert/strict";
import { startDials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import { namesToKeep, rideAfterImport } from "./gpxEdit.ts";

const NOW = { preset: "default" as const, dials: { ...startDials("default"), stress: 70, when: "weekend" as const } };

test("a file that names no ride type leaves the ride type and sliders as they are", () => {
  assert.deepEqual(rideAfterImport({ preset: null }, NOW), NOW);
});

test("a ride type the file names is chosen as the dialog chooses it: its sliders, the rider's ride time", () => {
  const ride = rideAfterImport({ preset: "group-ride" }, NOW);
  assert.equal(ride.preset, "group-ride");
  assert.deepEqual(ride.dials, startDials("group-ride", null, "weekend"));
  // Cargo Bike starts carrying cargo, as its card does.
  assert.equal(rideAfterImport({ preset: "cargo" }, NOW).dials.carrying, "cargo");
});

test("the file's own sliders are taken, fitted to the ride type as a link's are", () => {
  const ride = rideAfterImport({ preset: "group-ride", dials: { stress: 40, hills: -20 } }, NOW);
  assert.deepEqual(ride.dials, { ...startDials("group-ride", null, "weekend"), stress: 40, hills: -20 });
  // Mass Ride's traffic slider is locked at 0, whatever the file says.
  assert.equal(rideAfterImport({ preset: "mass-ride", dials: { stress: 80, hills: 50 } }, NOW).dials.stress, 0);
  assert.equal(rideAfterImport({ preset: "mass-ride", dials: { stress: 80, hills: 50 } }, NOW).dials.hills, 0);
  // A ride time in the file is the file's.
  assert.equal(rideAfterImport({ preset: "fast", dials: { stress: 10, hills: 0, when: "weekday_rush" } }, NOW).dials.when, "weekday_rush");
});

test("place names in a file are kept; RouteMaker's own Start, Stop (and the earlier Via) and End are not names", () => {
  const points: LonLat[] = [
    [-77, 38.9],
    [-77.01, 38.91],
    [-77.02, 38.92],
    [-77.03, 38.93],
  ];
  assert.deepEqual(namesToKeep({ points, pointNames: ["Start", "Via 1", "Stop 2", "Union Station", " "] }), [
    [points[3], "Union Station"],
  ]);
  assert.deepEqual(namesToKeep({ points }), []);
});
