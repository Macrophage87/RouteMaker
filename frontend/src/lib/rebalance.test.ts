// REBALANCE-RIDE (Stephen, 2026-10-12): Rebalance Ride, an Adventure ride type planned as a
// bikeshare trip from a crowded station to one that needs bikes (core.bikeshare, rebalance=True).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { PRESETS, presetLabel, twoPointsOnly, usesBikeshare } from "./presets.ts";
import { dialFields, fitDials, offersAssist, offersBike, startDials } from "./dials.ts";
import { activePins } from "./stations.ts";
import { RIDE_GROUPS, filterRideGroups } from "./rideTypeGroups.ts";
import { appSource } from "../testSupport/appSource.mjs";

// The operator's programme name, kept out of this file's own text so the scan below finds only the description.
const PROGRAMME = ["Bike", "Angels"].join(" ");

const DESCRIPTION =
  "Move a bikeshare bike from a crowded station to one that needs bikes. Rides like this can earn bikeshare reward points " +
  `(${PROGRAMME} in the Capital Bikeshare app); your points show there, not here.`;

test("Rebalance Ride is offered with the owner's exact description, and no number of points", () => {
  const option = PRESETS.find((p) => p.id === "rebalance");
  assert.ok(option);
  assert.equal(option.label, "Rebalance Ride");
  assert.equal(presetLabel("rebalance"), "Rebalance Ride");
  assert.equal(option.description, DESCRIPTION);
  assert.doesNotMatch(option.description, /\d/);
});

test("it is an Adventure ride type, and the search finds it by its description", () => {
  const adventure = RIDE_GROUPS.find((g) => g.id === "adventure");
  assert.ok(adventure?.ids.includes("rebalance"));
  for (const query of ["rebalance", "crowded", "reward points"]) {
    assert.deepEqual(
      filterRideGroups(query).map((g) => [g.id, [...g.ids]]),
      [["adventure", ["rebalance"]]],
      query,
    );
  }
});

test("the programme's name is in the description and nowhere else in the front end", () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const found: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else if (/\.(ts|tsx|mjs|js|css|html)$/.test(name) && !/\.test\./.test(name) && readFileSync(path, "utf8").includes(PROGRAMME)) {
        found.push(path.slice(root.length));
      }
    }
  };
  walk(root);
  assert.deepEqual(found, ["lib/presets.ts"]);
  const presets = readFileSync(new URL("./presets.ts", import.meta.url), "utf8");
  assert.equal(presets.split(PROGRAMME).length - 1, 1);
});

test("it is planned as a bikeshare trip: two points, the bike choice, no assist toggle", () => {
  assert.ok(usesBikeshare("rebalance"));
  assert.ok(usesBikeshare("bikeshare"));
  assert.ok(!usesBikeshare("bikeshare-transit"));
  assert.ok(twoPointsOnly("rebalance"));
  assert.ok(offersBike("rebalance"));
  assert.equal(offersAssist("rebalance"), false);
});

test("its sliders start as Bikeshare's, for each bike", () => {
  for (const bike of ["classic", "ebike"] as const) {
    const rebalance = startDials("rebalance", null, null, false, bike);
    const bikeshare = startDials("bikeshare", null, null, false, bike);
    assert.deepEqual(rebalance, bikeshare, bike);
  }
  assert.equal(startDials("rebalance").bike, "classic");
});

test("it never asks to end outside a dock; it sends the bike and a chosen station", () => {
  const fitted = fitDials("rebalance", { ...startDials("rebalance", null, null, false, "ebike"), ending: "outside_dock" });
  assert.equal(fitted.ending, undefined);
  const fields = dialFields({ ...fitted, pickupStation: "a", dropoffStation: "b" });
  assert.equal(fields.bike, "ebike");
  assert.equal(fields.ending, undefined);
  assert.equal(fields.pickup_station, "a");
  assert.equal(fields.dropoff_station, "b");
  // Bikeshare keeps its outside ending.
  assert.equal(fitDials("bikeshare", { ...startDials("bikeshare", null, null, false, "ebike"), ending: "outside_dock" }).ending, "outside_dock");
});

test("the station lists (crowded to pick up, low to return) and the route options show on it as on Bikeshare", () => {
  const start: [number, number] = [-77, 38.9];
  const end: [number, number] = [-77.04, 38.91];
  const pins = { pickup: { id: "a", name: "A", at: start }, dropoff: { id: "b", name: "B", at: end } };
  assert.deepEqual(activePins("rebalance", [start, end], pins), pins);
  const app = appSource();
  assert.match(app, /usesBikeshare\(preset\) && points\.length > 0 \? \(\s*<Fold title="Choose a station"/);
  assert.match(app, /mode === "go" && usesBikeshare\(preset\) && shown/);
});
