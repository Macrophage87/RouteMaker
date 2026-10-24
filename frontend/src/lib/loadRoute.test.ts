import { test } from "node:test";
import assert from "node:assert/strict";
import { gpxRideTypes, gpxStartRide, keptLine, loadRows, withGpxChoice } from "./loadRoute.ts";
import type { KeptRoute } from "./offlineRoutes.ts";
import type { SavedSummary } from "./savedRoutes.ts";

const saved: SavedSummary = { id: 7, name: "Dupont to Glen Echo", source: "plan", distance_m: 16093, preset: "default", created_at: "2026-10-15T12:00:00Z", updated_at: "2026-10-15T12:00:00Z" };
const kept = { id: "#p=x", plan: "#p=x", title: "Union Station loop", distanceM: 8047, savedAt: 0, lastRide: false } as unknown as KeptRoute;

test("Load route's rows: saved routes first, then the ones kept on this device, each a name and one short line", () => {
  const rows = loadRows([saved], [kept]);
  assert.deepEqual(
    rows.map((r) => [r.kind, r.name]),
    [
      ["saved", "Dupont to Glen Echo"],
      ["kept", "Union Station loop"],
    ],
  );
  assert.match(rows[0].detail, /^10(\.0)? mi .* · Saved Oct 15, 2026$/);
  assert.match(keptLine(kept), / · On this device$/);
  assert.match(keptLine({ ...kept, lastRide: true }), / · Last ride, on this device$/);
  assert.deepEqual(loadRows([], []), []);
});

test("Open GPX file offers every ride type but the transit ones, starting on the page's own", () => {
  const ids = gpxRideTypes().map((r) => r.id);
  assert.ok(ids.includes("default"));
  assert.ok(!ids.includes("bike-transit") && !ids.includes("bikeshare-transit"));
  assert.equal(gpxStartRide("trailmaxxing"), "trailmaxxing");
  assert.equal(gpxStartRide("bike-transit"), "default");
});

test("a file opens on the ride type chosen (its own sliders kept for the same one), followed as chosen", () => {
  const file = { preset: "default" as const, dials: { loop: true }, name: "a.gpx" };
  assert.deepEqual(withGpxChoice(file, { preset: "default", exact: true }), { ...file, exact: true });
  assert.deepEqual(withGpxChoice(file, { preset: "trailmaxxing", exact: false }), { ...file, preset: "trailmaxxing", dials: undefined, exact: false });
  assert.deepEqual(withGpxChoice({ preset: null, name: "b.gpx" }, { preset: "novice", exact: false }), { preset: "novice", name: "b.gpx", dials: undefined, exact: false });
});
