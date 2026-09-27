import { test } from "node:test";
import assert from "node:assert/strict";
import { FACILITY_CLASSES, avoidMetres, facilityRows } from "./facilityBar.ts";

test("the rows are the owner's four classes in his order, then the unrated", () => {
  assert.deepEqual(
    FACILITY_CLASSES.map((c) => c.key),
    ["path", "protected", "lane", "none", "unknown"],
  );
});

test("percentages add up to 100 and follow the metres", () => {
  const rows = facilityRows({ path: 1000, protected: 333, lane: 333, none: 334, unknown: 0 });
  assert.equal(rows.reduce((s, r) => s + r.percent, 0), 100);
  assert.equal(rows[0].percent, 50);
  assert.ok(rows.every((r) => r.label.length > 0));
});

test("an older API, or a route with nothing rated, shows no breakdown", () => {
  assert.deepEqual(facilityRows(undefined), []);
  assert.deepEqual(facilityRows({ unknown: 5000 }), []);
  assert.deepEqual(facilityRows({}), []);
});

test("junk values count as nothing", () => {
  const rows = facilityRows({ path: Number.NaN, protected: -5, lane: 100, none: Infinity });
  assert.equal(rows.find((r) => r.key === "lane")?.percent, 100);
});

test("the avoid warning reads tier 5 and nothing else", () => {
  assert.equal(avoidMetres({ "1": 100, "4": 900 }), 0);
  assert.equal(avoidMetres({ "5": 450 }), 450);
  assert.equal(avoidMetres({ "5": Number.NaN }), 0);
  assert.equal(avoidMetres(undefined), 0);
});
