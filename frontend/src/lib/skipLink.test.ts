// The skip link past the map's markers (a11y review of integrate-2; OWNER-DECISIONS 220).
import { test } from "node:test";
import assert from "node:assert/strict";
import { SKIP_LINK_TEXT, skipToPlanner } from "./skipLink.ts";
import { decodePlan } from "./planHash.ts";

test("the link moves the focus to the planner and keeps the address (the plan is in the fragment)", () => {
  let prevented = 0;
  let focused = 0;
  const went = skipToPlanner({ preventDefault: () => prevented++ }, { focus: () => focused++ });
  assert.equal(went, true);
  assert.equal(prevented, 1, "the browser does not follow #route-planner");
  assert.equal(focused, 1);
});

test("with no planner yet, it still keeps the address", () => {
  let prevented = 0;
  assert.equal(skipToPlanner({ preventDefault: () => prevented++ }, null), false);
  assert.equal(prevented, 1);
});

test("the premise: #route-planner in the address would be read as a plan with no points", () => {
  assert.deepEqual(decodePlan("#route-planner").points, []);
});

test("the link says where it goes", () => {
  assert.match(SKIP_LINK_TEXT, /^Skip to the route planner$/);
});
