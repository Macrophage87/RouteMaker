// Go keeps its route as it is on the map until Edit route is opened (Stephen 2026-11-20: stray taps changed loaded
// routes). Plan and Review are not locked here.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mapEditsLocked } from "./appMode.ts";

test("Go's route is locked on the map until Edit route is open", () => {
  assert.equal(mapEditsLocked("go", false), true);
  assert.equal(mapEditsLocked("go", true), false);
});

test("Plan stays free to change on the map", () => {
  assert.equal(mapEditsLocked("plan", false), false);
  assert.equal(mapEditsLocked("plan", true), false);
});
