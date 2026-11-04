// The page's own location checks at places spread over the map: city, suburb and country, in
// DC, Maryland, Virginia and West Virginia, and a few places outside it (the owner,
// 2026-11-04: "a mix of locations, as well as urban, suburban, and rural"). The places are
// fixtures/test-places.json, the same ones the server's tests use (tests/test_places.py).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { inDc, nearDc } from "./dcBoundary.ts";
import { insideCoverage, type LonLat } from "./geo.ts";

interface Place {
  name: string;
  setting?: string;
  lon: number;
  lat: number;
  dc?: boolean;
}

const places = JSON.parse(readFileSync(new URL("../../../fixtures/test-places.json", import.meta.url), "utf8")) as {
  inside: Place[];
  outside: Place[];
};

test("the places cover the city, the suburbs and the country", () => {
  assert.deepEqual(new Set(places.inside.map((p) => p.setting)), new Set(["urban", "suburban", "rural"]));
});

for (const place of places.inside) {
  const at: LonLat = [place.lon, place.lat];
  test(`${place.setting} ${place.name}: inside the map, and in DC only where it is`, () => {
    assert.equal(insideCoverage(at), true);
    assert.equal(inDc(at), place.dc);
    assert.equal(nearDc(at), place.dc, "none of the places sits on the District's edge");
  });
}

for (const place of places.outside) {
  test(`${place.name}: outside the map`, () => {
    assert.equal(insideCoverage([place.lon, place.lat]), false);
    assert.equal(inDc([place.lon, place.lat]), false);
  });
}
