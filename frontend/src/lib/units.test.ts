import { test } from "node:test";
import assert from "node:assert/strict";
import {
  QUARTER_MILE,
  formatAxisDistance,
  formatClimb,
  formatDistance,
  formatExtra,
  formatMileMarker,
  formatMilePost,
  formatMileRange,
  formatMilesCapped,
  formatSpeed,
  formatStationDistance,
  markerFigure,
  spokenDistance,
  unitsFirst,
  unitsFirstDeep,
} from "./format.ts";
import { formatClimbSpoken, formatDistanceSpoken } from "./spokenFigures.ts";
import { chooseUnits, readUnits, setUnitsForTest, units, type Units } from "./units.ts";
import { applyToDevice, deviceSettings, parseSettings } from "./accountSettings.ts";
import { parseTarget, targetText } from "./dialsPanel.ts";
import { paceOptions } from "./runPace.ts";
import { topoLabelExpression } from "./topoLines.ts";
import { calmDistance, mileWord } from "./profileChart.ts";
import { roadHazardWords } from "./navigate.ts";

class Memory {
  map = new Map<string, string>();
  getItem(key: string): string | null {
    return this.map.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.map.set(key, value);
  }
  removeItem(key: string): void {
    this.map.delete(key);
  }
}

/** Run `body` with the units set, then back to US (the default every other test expects). */
function inUnits(next: Units, body: () => void): void {
  setUnitsForTest(next);
  try {
    body();
  } finally {
    setUnitsForTest("us");
  }
}

test("US is the default: miles first, metric in brackets, as before", () => {
  assert.equal(units(), "us");
  assert.equal(readUnits(new Memory()), "us");
  assert.equal(formatDistance(7_600), "4.7 mi (7.6 km)");
  assert.equal(formatDistance(150), "490 ft (150 m)");
  assert.equal(formatSpeed(19.3), "12 mph (19 km/h)");
  assert.equal(formatClimb(81), "266 ft (81 m)");
  assert.equal(spokenDistance(150), "500 feet");
});

test("metric mode turns every figure round: kilometres, metres and km/h first, US in brackets", () => {
  inUnits("metric", () => {
    assert.equal(formatDistance(7_600), "7.6 km (4.7 mi)");
    assert.equal(formatDistance(150), "150 m (490 ft)");
    assert.equal(formatSpeed(19.3), "19 km/h (12 mph)");
    assert.equal(formatClimb(81), "81 m (266 ft)");
    assert.equal(formatExtra(1_900), "+1.9 km (1.2 mi)");
    assert.equal(formatMileRange(1_770, 2_900), "1.8 to 2.9 km (1.1 to 1.8 mi)");
    assert.equal(formatStationDistance(320), "320 m (0.2 mi)");
    assert.equal(formatAxisDistance(6_437), "6.4 km (4 mi)");
    assert.equal(formatMilesCapped(7_600), "7.6 km");
    assert.equal(formatMileMarker(20_000), "20.0 km (12.4 mi)");
    assert.equal(markerFigure(20_000), "20.0");
    assert.equal(formatMilePost(20_000), "km 20.0 (mile 12.4)");
    assert.equal(calmDistance(11_900), "11.9 calm km (7.4 calm mi)");
    assert.equal(mileWord(6_800), "Km 6.8");
  });
});

test("Ride's voice says one unit: metres to just under a kilometre, then kilometres to a tenth", () => {
  inUnits("metric", () => {
    assert.equal(spokenDistance(14), "10 meters");
    assert.equal(spokenDistance(240), "250 meters");
    assert.equal(spokenDistance(720), "700 meters");
    assert.equal(spokenDistance(1_000), "1 kilometer");
    assert.equal(spokenDistance(1_460), "1.5 kilometers");
    assert.equal(spokenDistance(3_000), "3 kilometers");
    assert.equal(formatDistanceSpoken(12_340), "12.3 kilometers");
    assert.equal(formatClimbSpoken(104), "104 meters");
  });
});

test("decimals, never fractions: the ride dots' reach is 0.25 mi (400 m)", () => {
  assert.equal(QUARTER_MILE, "0.25 mi (400 m)");
  assert.doesNotMatch(QUARTER_MILE, /quarter|¼/);
});

test("the server's words are turned round in metric mode and back in US mode; names and plain numbers untouched", () => {
  const said = "Rails in the road on H Street Northeast, 0.4 to 1.2 mi (0.6 to 1.9 km): cross them square on.";
  inUnits("metric", () => {
    assert.equal(unitsFirst(said), "Rails in the road on H Street Northeast, 0.6 to 1.9 km (0.4 to 1.2 mi): cross them square on.");
    assert.equal(unitsFirst("1.2 mi (1.9 km), for 300 ft (91 m)"), "1.9 km (1.2 mi), for 91 m (300 ft)");
    assert.equal(unitsFirst("Speed 25 mph (40 km/h), posted"), "Speed 40 km/h (25 mph), posted");
    assert.equal(unitsFirst("Spanish: 0.4 a 1.2 mi (0.6 a 1.9 km)"), "Spanish: 0.6 a 1.9 km (0.4 a 1.2 mi)");
    assert.equal(unitsFirst("I-395 near mi casa"), "I-395 near mi casa");
    // Ride's short hazard line still reads the turned-round sentence.
    assert.equal(roadHazardWords(unitsFirst(said)), "Rails in the road on H Street Northeast. Cross them square on.");
  });
  // A route kept while metric was chosen reads miles first again in US mode.
  assert.equal(unitsFirst("0.6 to 1.9 km (0.4 to 1.2 mi)"), "0.4 to 1.2 mi (0.6 to 1.9 km)");
});

test("an answer turned round keeps every part it did not change, the same object (the departure's clock is kept by identity)", () => {
  const departure = { at: "2026-11-03T08:00:00", line: "Red" };
  const answer = { distance_m: 5, geometry: { coordinates: [[1, 2]] }, transit: { departure }, description: [{ text: "0.0 to 1.2 mi (0.0 to 1.9 km)" }] };
  inUnits("metric", () => {
    const out = unitsFirstDeep(answer);
    assert.notEqual(out, answer);
    assert.equal(out.transit.departure, departure);
    assert.equal(out.geometry, answer.geometry);
    assert.equal(out.description[0].text, "0.0 to 1.9 km (0.0 to 1.2 mi)");
    assert.equal(unitsFirstDeep(out), out, "a second pass changes nothing");
  });
  assert.equal(unitsFirstDeep({ transit: { departure } }).transit.departure, departure);
});

test("the target distance is typed in km in metric mode, in miles otherwise", () => {
  assert.equal(parseTarget("10"), Math.round(10 * 1609.344));
  assert.equal(targetText(16_093), "10");
  inUnits("metric", () => {
    assert.equal(parseTarget("10"), 10_000);
    assert.equal(parseTarget("10 km"), 10_000);
    assert.equal(targetText(16_093), "16.1");
  });
});

test("the run pace, the contour labels: the rider's units first", () => {
  assert.match(paceOptions()[0][1], /per mile \(.* per km\)$/);
  assert.equal(JSON.stringify(topoLabelExpression()).indexOf(" ft (") > 0, true);
  inUnits("metric", () => {
    assert.match(paceOptions()[0][1], /per km \(.* per mile\)$/);
    assert.equal(JSON.stringify(topoLabelExpression()).indexOf(" m (") > 0, true);
  });
});

test("the choice is kept in this browser and with the account; a browser that will not keep it is not reloaded", async () => {
  const store = new Memory();
  store.setItem("routemaker.units", "metric");
  assert.equal(readUnits(store), "metric");
  assert.equal(deviceSettings(null, store).units, "metric");
  assert.equal(parseSettings({ v: 1, units: "metric" })?.units, "metric");
  assert.equal(parseSettings({ v: 1, units: "imperial" })?.units, undefined);
  const other = new Memory();
  applyToDevice({ v: 1, units: "metric" }, other);
  assert.equal(other.getItem("routemaker.units"), "metric");
  // Storage refused: the choice cannot be read back after a reload, so nothing is saved or reloaded.
  let saved = false;
  const refusing = { getItem: () => null, setItem: () => { throw new Error("full"); }, removeItem: () => {} };
  await chooseUnits("metric", async () => { saved = true; }, refusing);
  assert.equal(saved, false);
  assert.equal(units(), "us");
});
