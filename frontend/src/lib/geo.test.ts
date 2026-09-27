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

test("a via goes where the whole route is shortest, not merely near a point", () => {
  // The mutation reviewer's probe: points not evenly spaced, the click off the
  // line. Every insertion position is tried and the chosen one must be the
  // shortest total path.
  const a: LonLat = [-77.1, 38.9];
  const b: LonLat = [-76.9, 38.9];
  const c: LonLat = [-76.89, 38.9];
  const p: LonLat = [-76.92, 38.92];
  const chosen = addPoint([a, b, c], p);
  const options = [1, 2].map((i) => {
    const route = [a, b, c];
    route.splice(i, 0, p);
    return pathLengthM(route);
  });
  assert.equal(pathLengthM(chosen), Math.min(...options));
  assert.deepEqual(chosen, [a, p, b, c]);
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
  assert.equal(insideCoverage([-75.5, 39.0]), false); // east
  assert.equal(insideCoverage([-77.0, 39.8]), false); // north of Mason-Dixon
  assert.equal(insideCoverage([-78.5, 38.9]), false); // west
  assert.equal(insideCoverage([-77.0, 38.0]), false); // south
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

test("the detour thresholds: twice the straight line and 3 km more", () => {
  const BALTIMORE: LonLat = [-76.6122, 39.2904];
  const far = haversineM(DUPONT, BALTIMORE);
  assert.equal(detour([DUPONT, BALTIMORE], far * 1.5).flagged, false, "1.5x on a long trip");
  assert.equal(detour([DUPONT, BALTIMORE], far * 1.99).flagged, false, "just under 2x");
  assert.equal(detour([DUPONT, BALTIMORE], far * 2.0).flagged, true, "2x and 60 km more");
  const near = haversineM(DUPONT, CAPITOL);
  assert.equal(detour([DUPONT, CAPITOL], near * 4).flagged, true, "4x, about 10.8 km more");
  // 2.5x but under 3 km more: not worth a notice; 3.1 km more on the same hop is.
  const hop: LonLat = [-77.0434, 38.9266];
  const short = haversineM(DUPONT, hop);
  assert.ok(short * 1.5 < 3000);
  assert.equal(detour([DUPONT, hop], short * 2.5).flagged, false);
  assert.equal(detour([DUPONT, hop], short + 3100).flagged, true);
});

test("a route whose ends coincide is not a detour, and not Infinity times anything", () => {
  const result = detour([DUPONT, DUPONT], 5000);
  assert.equal(result.flagged, false);
  assert.ok(Number.isFinite(result.ratio));
});

test("tile maths lands a DC point on the tile that contains it", () => {
  const { x, y } = lonLatToTile(DUPONT, 12);
  assert.equal(x, 1171);
  assert.equal(y, 1566);
  const z0 = lonLatToTile(DUPONT, 0);
  assert.deepEqual([z0.x, z0.y], [0, 0]);
});
