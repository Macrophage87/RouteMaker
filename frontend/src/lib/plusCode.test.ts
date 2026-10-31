/**
 * Plus codes in the search box (Stephen, 2026-10-31). Cases from the Open Location Code project's own test data
 * (github.com/google/open-location-code, test_data/decoding.csv and shortCodeTests.csv, Apache 2.0).
 */
import assert from "node:assert/strict";
import test from "node:test";
import { COVERAGE_CENTRE, decodePlusCode, isFullPlusCode, isShortPlusCode, isValidPlusCode, parsePlusCode, recoverPlusCode } from "./plusCode.ts";

const near = (a: readonly number[] | null | undefined, b: readonly number[], eps = 1e-6) => {
  assert.ok(a, "a point");
  assert.ok(Math.abs(a[0] - b[0]) < eps && Math.abs(a[1] - b[1]) < eps, `${a} near ${b}`);
};

test("full codes decode to the centre of their area (decoding.csv)", () => {
  // code, latLo, lngLo, latHi, lngHi
  const cases: Array<[string, number, number, number, number]> = [
    ["7FG49QCJ+2V", 20.37, 2.782125, 20.370125, 2.78225],
    ["7FG49QCJ+2VX", 20.3701, 2.78221875, 20.370125, 2.78225],
    ["7FG49QCJ+2VXGJ", 20.370113, 2.782234375, 20.370114, 2.78223632813],
    ["8FVC2222+22", 47.0, 8.0, 47.000125, 8.000125],
    ["4VCPPQGP+Q9", -41.273125, 174.785875, -41.273, 174.786],
    ["22222222+22", -90.0, -180.0, -89.999875, -179.999875],
    ["6FH32222+222", 1, 1, 1.000025, 1.00003125],
    ["849VGJQF+VX7QR3J", 37.53966912, -122.3750698242, 37.53966916, -122.3750697021],
    ["849VGJQF+VX7QR3J7QR3J", 37.53966912, -122.3750698242, 37.53966916, -122.3750697021],
    ["55CJG366+PP", -21.48825, -107.93825, -21.488125, -107.938125],
  ];
  for (const [code, s, w, n, e] of cases) near(decodePlusCode(code), [(w + e) / 2, (s + n) / 2], 1e-7);
});

test("short codes are recovered nearest the reference point (shortCodeTests.csv, recovery)", () => {
  // full code, reference lat, reference lng, short code
  const cases: Array<[string, number, number, string]> = [
    ["9C3W9QCJ+2VX", 51.3701125, -1.217765625, "+2VX"],
    ["9C3W9QCJ+2VX", 51.3708675, -1.217765625, "CJ+2VX"],
    ["9C3W9QCJ+2VX", 51.3852125, -1.217765625, "9QCJ+2VX"],
    ["9C3W9QCJ+2VX", 51.3701125, -1.202665625, "9QCJ+2VX"],
    ["8FVC2GGG+GG", 46.976, 8.526, "2GGG+GG"],
    ["8FRCXGGG+GG", 47.026, 8.526, "XGGG+GG"],
    ["8FR9GXGG+GG", 46.526, 8.026, "GXGG+GG"],
    ["8FRCG2GG+GG", 46.526, 7.976, "G2GG+GG"],
    ["CFX22222+22", 89.6, 0.0, "2222+22"],
    ["2CXXXXXX+XX", -81.0, 0.0, "XXXXXX+XX"],
    ["8FRCG2GG+GG", 46.526, 7.976, "8frCG2GG+gG"],
  ];
  for (const [full, lat, lng, short] of cases) {
    if (short === "+2VX") {
      // Not a code this box takes: nothing before the separator.
      assert.equal(isValidPlusCode(short), false);
      continue;
    }
    near(recoverPlusCode(short, [lng, lat]), decodePlusCode(full)!, 1e-7);
  }
});

test("which strings are plus codes", () => {
  assert.ok(isFullPlusCode("87C4VXQ7+GV"));
  assert.ok(isShortPlusCode("VXQ7+GV"));
  assert.ok(!isFullPlusCode("VXQ7+GV"));
  for (const not of ["", "VXQ7GV", "VXQ+7GV", "87C4VXQ7+G", "87C4VXQ7+GV+", "A2+22", "87C40000+GV", "87C0VX00+", "C++"]) {
    assert.equal(isValidPlusCode(not), false, not);
  }
});

test("a code typed in the box: the place, its code as its name, a town after it ignored", () => {
  // A spot by the Capitol (38.889, -77.002).
  const mall = parsePlusCode("87C4VXQX+P3");
  assert.equal(mall?.code, "87C4VXQX+P3");
  near(mall?.point, [-77.0023125, 38.8893125]);
  // Google Maps' short form with a town, placed near the middle of the map.
  const short = parsePlusCode("vxqx+p3 Washington, District of Columbia");
  assert.equal(short?.code, "VXQX+P3");
  near(short?.point, mall!.point);
  // A spot in Baltimore (39.25, -76.61): its short code from the middle of the map and from a start there.
  const baltimore = decodePlusCode("87F5793Q+5W")!;
  near(baltimore, [-76.6101875, 39.2529375]);
  near(parsePlusCode("793Q+5W Baltimore")?.point, baltimore);
  near(parsePlusCode("793Q+5W", [-76.6, 39.3])?.point, baltimore);
  // The map's west edge (39.6, -77.9) is more than half a degree from its middle: a short code there is placed by
  // the start or the view; from the middle alone it would land a degree south and east.
  const west = decodePlusCode("87F4J422+22")!;
  near(west, [-77.8999375, 39.6000625]);
  near(parsePlusCode("J422+22", [-77.8, 39.5])?.point, west);
  near(parsePlusCode("J422+22")?.point, [west[0] + 1, west[1] - 1]);
  assert.ok(Math.abs(COVERAGE_CENTRE[1] - 38.96) < 0.01);
  // Not a place: a region (padding, or no digits after a short code's separator), or not a code at all.
  assert.equal(parsePlusCode("87C40000+"), null);
  assert.equal(parsePlusCode("VXQ7+"), null);
  assert.equal(parsePlusCode("1600 Pennsylvania Ave"), null);
  assert.equal(parsePlusCode("C++ meetup"), null);
  // Numbers alone are searched, not read as a code.
  for (const text of ["22+22", "45+67", "2345+67"]) assert.equal(parsePlusCode(text), null, text);
});
