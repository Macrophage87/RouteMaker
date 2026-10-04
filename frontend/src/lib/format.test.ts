// The one formatter: US customary first, metric in brackets (OWNER-DECISIONS 85).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  AVOID_MAX_SPAN_M,
  FEET_BELOW_M,
  SEEK_MAX_SPAN_M,
  formatClimb,
  formatDistance,
  formatDuration,
  formatExtra,
  formatPerMile,
  formatRoughDistance,
  formatSeconds,
  formatSpeed,
  milesFigure,
} from "./format.ts";

test("a distance is miles first, kilometres in brackets, to one place", () => {
  assert.equal(formatDistance(7600), "4.7 mi (7.6 km)");
  assert.equal(formatDistance(5480), "3.4 mi (5.5 km)");
  assert.equal(formatDistance(1609.344), "1.0 mi (1.6 km)");
  assert.equal(milesFigure(12_300), "7.6");
});

test("below a tenth of a mile a distance is feet, metres in brackets, to the nearest ten from a hundred", () => {
  assert.equal(FEET_BELOW_M, 160.9344);
  assert.equal(formatDistance(152), "500 ft (150 m)");
  assert.equal(formatDistance(160.9), "530 ft (160 m)");
  assert.equal(formatDistance(FEET_BELOW_M), "0.1 mi (0.2 km)");
  assert.equal(formatDistance(20), "66 ft (20 m)");
  assert.equal(formatDistance(0), "0 ft (0 m)");
});

test("a very long ride keeps its tenth of a mile", () => {
  assert.equal(formatDistance(647_400), "402.3 mi (647.4 km)");
  assert.equal(formatDistance(1_000_000), "621.4 mi (1000.0 km)");
});

test("a round limit or span is whole miles and kilometres", () => {
  assert.equal(formatRoughDistance(SEEK_MAX_SPAN_M), "31 mi (50 km)");
  assert.equal(formatRoughDistance(162_000), "101 mi (162 km)");
  assert.equal(formatRoughDistance(200_000), "124 mi (200 km)");
  assert.equal(formatRoughDistance(AVOID_MAX_SPAN_M), "16 mi (25 km)");
});

test("a climb is feet first, metres in brackets, rounded", () => {
  assert.equal(formatClimb(81), "266 ft (81 m)");
  assert.equal(formatClimb(31.3), "103 ft (31 m)");
  assert.equal(formatClimb(0), "0 ft (0 m)");
  assert.equal(formatClimb(0.2), "1 ft (0 m)");
});

test("a speed is mph first, km/h in brackets", () => {
  assert.equal(formatSpeed(19.3), "12 mph (19 km/h)");
  assert.equal(formatSpeed(9.66), "6 mph (10 km/h)");
  assert.equal(formatSpeed(0), "0 mph (0 km/h)");
});

test("duration reads as minutes, then hours and minutes", () => {
  assert.match(formatDuration(1296), /^22 min$/);
  assert.match(formatDuration(3900), /^1 h 05 min$/);
  assert.match(formatDuration(20), /^1 min$/);
  assert.match(formatDuration(5400), /^1 h 30 min$/);
  assert.match(formatDuration(3599), /^1 h 00 min$/);
});

test("nonsense in gives a dash, not NaN", () => {
  for (const f of [formatDistance, formatDuration, formatClimb, formatSpeed, formatRoughDistance]) {
    assert.equal(f(Number.NaN), "–");
    assert.equal(f(-1), "–");
    assert.equal(f(Number.POSITIVE_INFINITY), "–");
  }
});

test("a count of seconds is singular at one and carries its number", () => {
  assert.doesNotMatch(formatSeconds(1), /seconds/);
  assert.match(formatSeconds(1), /^1 \S+$/);
  for (const n of [2, 5, 60]) {
    assert.match(formatSeconds(n), new RegExp(`^${n} `));
    assert.notEqual(formatSeconds(n).replace(String(n), ""), formatSeconds(1).replace("1", ""), `${n}`);
  }
});

test("nothing in the app writes a unit but this module", async () => {
  // Metric first anywhere else would be the change undone (OWNER-DECISIONS 85).
  const { readdirSync, readFileSync, statSync } = await import("node:fs");
  const { join } = await import("node:path");
  const root = new URL("..", import.meta.url).pathname;
  const offenders: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) {
        if (name !== "rail-data" && name !== "licences") walk(path);
        continue;
      }
      if (!/\.(ts|tsx)$/.test(name) || /\.test\./.test(name) || name === "format.ts") continue;
      readFileSync(path, "utf8").split("\n").forEach((line, i) => {
        const code = line
          .replace(/\/\/.*$/, "")
          .replace(/^\s*\*.*$/, "")
          .replace(/\/\*\*.*\*\//, "")
          .replace(/\}mi\.gpx/, "}");
        // Spelled-out units and JSX text too (the units review, round 1: M16, M18, M19).
        if (/(\}|\d)\s*(km|mi|ft|m|mph|km\/h|kilomet(re|er)s?|metres?|meters?|miles?|feet|foot)\b/.test(code)) {
          offenders.push(`${path}:${i + 1}: ${line.trim()}`);
        }
      });
    }
  };
  walk(root);
  assert.deepEqual(offenders, []);
});

test("the map's scale shows miles and feet over kilometres and metres", async () => {
  const { readFileSync } = await import("node:fs");
  const view = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  const metric = view.indexOf('new maplibregl.ScaleControl({ unit: "metric" })');
  const imperial = view.indexOf('new maplibregl.ScaleControl({ unit: "imperial" })');
  // A bottom corner stacks upwards: the control added last is on top.
  assert.ok(metric > 0 && imperial > metric);
});

test("the hills slider's notes name their own limits", async () => {
  const { AVOID_NOTE, SEEK_NOTE } = await import("./dialsPanel.ts");
  assert.match(SEEK_NOTE, /up to 31 mi \(50 km\) apart\.$/);
  assert.match(AVOID_NOTE, /up to 16 mi \(25 km\) apart\.$/);
});

test("an extra distance reads miles first, with a sign, and nothing for what cannot be one", () => {
  assert.equal(formatExtra(1931.2), "+1.2 mi (1.9 km)");
  assert.equal(formatExtra(0), "+0.0 mi (0.0 km)");
  assert.equal(formatExtra(28968.2), "+18.0 mi (29.0 km)");
  assert.equal(formatExtra(-5), "–");
  assert.equal(formatPerMile(0.585), "0.6 mi (1.0 km)");
  assert.equal(formatPerMile(1.824), "1.8 mi (2.9 km)");
  assert.equal(formatPerMile(0.01), "0.1 mi (0.2 km)");
  assert.equal(formatPerMile(10), "10 mi (16 km)");
  assert.equal(formatPerMile(Number.NaN), "–");
  assert.equal(formatExtra(Number.NaN), "–");
});

test("a rule's range says miles or pounds first, metric in brackets (the a11y review's N3)", async () => {
  const { milesRange, poundsRange } = await import("./format.ts");
  assert.equal(milesRange(0.7, 621, 1_000, 1_000_000), "0.7 to 621 miles (1 to 1,000 km)");
  assert.equal(poundsRange(150, 309, 68, 140), "150 to 309 pounds (68 to 140 kg)");
});
