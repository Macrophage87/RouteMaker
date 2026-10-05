import { test } from "node:test";
import assert from "node:assert/strict";
import {
  PLAN_KEY,
  SKIP_SIGN_IN_PLAN_WITH_LOCATION,
  planToOpen,
  rememberPlan,
  rememberPlanForSignIn,
  type StorageLike,
} from "./signIn.ts";

function memory(): StorageLike & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
    removeItem: (k) => void data.delete(k),
  };
}

const PLAN = "#p=-77.04340,38.90960;-77.00910,38.88990&preset=mass-ride";

test("a plan survives the sign-in round trip, once", () => {
  const storage = memory();
  rememberPlan(storage, PLAN);
  assert.equal(planToOpen(storage, ""), PLAN, "the callback lands on / with no fragment");
  assert.equal(planToOpen(storage, ""), "", "used once, not on every later visit");
});

test("a link with its own plan wins over a remembered one", () => {
  const storage = memory();
  rememberPlan(storage, PLAN);
  const other = "#p=-77.06,38.90;-77.07,38.89&preset=default";
  assert.equal(planToOpen(storage, other), other);
  assert.equal(storage.data.has(PLAN_KEY), false);
});

test("a preset link wins over a remembered plan", () => {
  // /trailmaxxing redirects to /#preset=trailmaxxing: a plan of its own, with no points.
  for (const link of ["#preset=trailmaxxing", "#v=1&preset=gravel"]) {
    const storage = memory();
    rememberPlan(storage, PLAN);
    assert.equal(planToOpen(storage, link), link);
    assert.equal(storage.data.has(PLAN_KEY), false, "the remembered plan is dropped, not kept for later");
  }
});

test("a hash with neither points nor a ride type still gets the remembered plan", () => {
  const storage = memory();
  rememberPlan(storage, PLAN);
  assert.equal(planToOpen(storage, "#v=1&xpreset=gravel"), PLAN);
});

test("nothing is remembered when there is no plan", () => {
  const storage = memory();
  rememberPlan(storage, "#preset=default");
  assert.equal(storage.data.size, 0);
});

test("storage that refuses is not an error", () => {
  const refusing: StorageLike = {
    getItem: () => {
      throw new Error("denied");
    },
    setItem: () => {
      throw new Error("denied");
    },
    removeItem: () => {
      throw new Error("denied");
    },
  };
  rememberPlan(refusing, PLAN);
  assert.equal(planToOpen(refusing, ""), "");
  assert.equal(planToOpen(null, PLAN), PLAN);
});

test("a plan holding the rider's location is kept for the round trip for now, and the switch skips it", () => {
  // OWNER-DECISIONS 395, owner decision pending: kept in this tab's sessionStorage, read once.
  assert.equal(SKIP_SIGN_IN_PLAN_WITH_LOCATION, false);
  const kept = memory();
  rememberPlanForSignIn(kept, PLAN, true);
  assert.equal(planToOpen(kept, ""), PLAN);
  assert.equal(kept.data.size, 0, "read once and removed");
  const skipped = memory();
  rememberPlanForSignIn(skipped, PLAN, true, true);
  assert.equal(skipped.data.size, 0, "with the switch on, a plan with a location is not kept");
  rememberPlanForSignIn(skipped, PLAN, false, true);
  assert.equal(planToOpen(skipped, ""), PLAN, "a plan without one still is");
});
