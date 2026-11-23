import { test } from "node:test";
import assert from "node:assert/strict";
import { COVERAGE_BBOX, areaOf, coverageEnvelope, insideCoverage, setCoverageAreas, type Box, type LonLat } from "./geo.ts";
import { coverageBoxes, coverageMask, fetchCoverage, type Coverage } from "./mapGlue.ts";

// A map of two areas (the owner, 2026-11-23): DC to Baltimore and Southwest Florida.
const FLORIDA: Box = [-82.75, 25.65, -80.70, 27.45];
const BONITA_SPRINGS: LonLat = [-81.7787, 26.3398];
const WHITE_HOUSE: LonLat = [-77.0365, 38.8977];
const JACKSONVILLE: LonLat = [-81.6557, 30.3322];

function ring([w, s, e, n]: Box): number[][] {
  return [[w, s], [e, s], [e, n], [w, n], [w, s]];
}

const TWO: Coverage = {
  type: "Feature",
  geometry: { type: "MultiPolygon", coordinates: [[ring(COVERAGE_BBOX)], [ring(FLORIDA)]] },
  properties: {},
};

test("the home box alone until the API serves more areas", () => {
  setCoverageAreas([COVERAGE_BBOX]);
  assert.equal(insideCoverage(WHITE_HOUSE), true);
  assert.equal(insideCoverage(BONITA_SPRINGS), false);
});

test("with two areas a point is covered in either and not between them", () => {
  setCoverageAreas(coverageBoxes(TWO));
  try {
    assert.deepEqual(areaOf(BONITA_SPRINGS), FLORIDA);
    assert.equal(insideCoverage(WHITE_HOUSE), true);
    assert.equal(insideCoverage(JACKSONVILLE), false);
    assert.deepEqual(coverageEnvelope(), [-82.75, 25.65, -76.02, 39.72]);
  } finally {
    setCoverageAreas([COVERAGE_BBOX]);
  }
});

test("the mask has one hole and one edge per area", () => {
  const mask = coverageMask(TWO);
  const holes = mask.features[0].geometry.coordinates as number[][][];
  assert.equal(holes.length, 3); // the world, then a hole each
  assert.equal(mask.features.filter((f) => f.properties.part === "edge").length, 2);
});

test("a MultiPolygon coverage is taken", async () => {
  const answer = (async () => new Response(JSON.stringify(TWO), { status: 200 })) as unknown as typeof fetch;
  const got = await fetchCoverage("https://example.test", answer);
  assert.ok(got);
  assert.deepEqual(coverageBoxes(got), [COVERAGE_BBOX, FLORIDA]);
});
