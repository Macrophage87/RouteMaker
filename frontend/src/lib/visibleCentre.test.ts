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

test("Go's you dot is a marker of its own: the ride's rider prop (which stops route framing) stays the ride's only", async () => {
  const { readFileSync } = await import("node:fs");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /rider=\{riding && rideView\?\.rider \? rideView\.rider : roaming \? roamRider : null\}/);
  assert.match(app, /youDot=\{!onBike && mode === "go" && points\.length === 0 && goStart\.kind === "here" \? goStart\.point : null\}/);
  const map = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  // The route is framed unless riding; the you dot has no say in it.
  assert.match(map, /if \(!route \|\| stale \|\| route\.geometry\.coordinates\.length < 2 \|\| props\.rider\) return;/);
  assert.doesNotMatch(map, /youDot[^\n]*(easeTo|flyTo|fitBounds)/);
});
