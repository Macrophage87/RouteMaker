import { test } from "node:test";
import assert from "node:assert/strict";
import {
  COVERAGE_BBOX,
  MAX_POINTS,
  addPoint,
  detour,
  haversineM,
  insideCoverage,
  lonLatToTile,
  pathLengthM,
  type LonLat,
} from "./geo.ts";

const DUPONT: LonLat = [-77.0434, 38.9096];
const CAPITOL: LonLat = [-77.0091, 38.8899];

test("haversine is symmetric, zero on itself, and about right for a known pair", () => {
  assert.equal(haversineM(DUPONT, DUPONT), 0);
  assert.equal(haversineM(DUPONT, CAPITOL), haversineM(CAPITOL, DUPONT));
  const d = haversineM(DUPONT, CAPITOL);
  assert.ok(d > 3500 && d < 3700, `${d}`);
});

test("path length is the sum of its legs", () => {
  const via: LonLat = [-77.03, 38.9];
  assert.ok(
    Math.abs(pathLengthM([DUPONT, via, CAPITOL]) - haversineM(DUPONT, via) - haversineM(via, CAPITOL)) < 1e-6,
  );
  assert.equal(pathLengthM([DUPONT]), 0);
});

test("the first click is the start and the second the end", () => {
  const one = addPoint([], DUPONT);
  assert.deepEqual(one, [DUPONT]);
  const two = addPoint(one, CAPITOL);
  assert.deepEqual(two, [DUPONT, CAPITOL]);
});

test("a later click becomes a via on the leg it adds least to, keeping both ends", () => {
  const a: LonLat = [-77.1, 38.9];
  const b: LonLat = [-77.0, 38.9];
  const c: LonLat = [-76.9, 38.9];
  const nearFirstLeg: LonLat = [-77.05, 38.91];
  const nearSecondLeg: LonLat = [-76.95, 38.91];
  const route = [a, c];
  const withB = addPoint(route, b);
  assert.deepEqual(withB, [a, b, c]);
  assert.deepEqual(addPoint(withB, nearFirstLeg), [a, nearFirstLeg, b, c]);
  assert.deepEqual(addPoint(withB, nearSecondLeg), [a, b, nearSecondLeg, c]);
});

test("adding never mutates the list it was given", () => {
  const route: LonLat[] = [DUPONT, CAPITOL];
  const frozen = JSON.stringify(route);
  addPoint(route, [-77.03, 38.9]);
  assert.equal(JSON.stringify(route), frozen);
});

test("no more than the API's twenty-five points", () => {
  let route: LonLat[] = [];
  for (let i = 0; i < 40; i += 1) route = addPoint(route, [-77 + i / 1000, 38.9]);
  assert.equal(route.length, MAX_POINTS);
  assert.equal(MAX_POINTS, 25);
});

test("the coverage box is the settings' one and clicks outside it are refused", () => {
  assert.deepEqual(COVERAGE_BBOX, [-78.0, 38.2, -76.02, 39.72]);
  assert.equal(insideCoverage(DUPONT), true);
  assert.equal(insideCoverage([-76.61, 39.29]), true); // Baltimore
  assert.equal(insideCoverage([-75.5, 39.0]), false);
  assert.equal(insideCoverage([-77.0, 39.8]), false); // north of Mason-Dixon
});

test("a detour is flagged when the route is far longer than the straight line", () => {
  const straight = haversineM(DUPONT, CAPITOL);
  assert.equal(detour([DUPONT, CAPITOL], straight * 1.3).flagged, false);
  const long = detour([DUPONT, CAPITOL], 141_000);
  assert.equal(long.flagged, true);
  assert.ok(long.ratio > 30);
  // A short hop that doubles is not worth a notice.
  const hop: LonLat = [-77.0434, 38.9106];
  assert.equal(detour([DUPONT, hop], haversineM(DUPONT, hop) * 3).flagged, false);
});

test("tile maths lands a DC point on the tile that contains it", () => {
  const { x, y } = lonLatToTile(DUPONT, 12);
  assert.equal(x, 1171);
  assert.equal(y, 1566);
  const z0 = lonLatToTile(DUPONT, 0);
  assert.deepEqual([z0.x, z0.y], [0, 0]);
});
