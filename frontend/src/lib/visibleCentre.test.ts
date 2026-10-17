import { test } from "node:test";
import assert from "node:assert/strict";
import { visibleCentreOffset } from "./visibleCentre.ts";

const phone = { left: 0, top: 0, right: 393, bottom: 764 };

test("on a phone, the centre is between Go's bar and the sheet", () => {
  // Bar to 64 px, sheet from 400 px: the open map's middle is at 232, 150 px above the container's 382.
  assert.deepEqual(visibleCentreOffset(phone, 64, { left: 0, top: 400, right: 393, bottom: 764 }, true), [0, -150]);
});

test("wider, the centre is right of the panel card", () => {
  const map = { left: 0, top: 0, right: 1280, bottom: 800 };
  assert.deepEqual(visibleCentreOffset(map, 0, { left: 12, top: 64, right: 412, bottom: 788 }, false), [206, 0]);
});

test("no panel, or a panel off the map, leaves the plain centre", () => {
  assert.deepEqual(visibleCentreOffset(phone, 0, null, true), [0, 0]);
  assert.deepEqual(visibleCentreOffset(phone, 0, { left: 0, top: 900, right: 393, bottom: 1200 }, true), [0, 0]);
});
