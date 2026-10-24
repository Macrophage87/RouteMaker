/** A map card kept clear of the Go sheet (lib/popupFit.ts; Stephen 2026-10-19, the Metro card under the panel). */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { popupPan } from "./popupFit.ts";

const room = { top: 16, left: 8, right: 382, bottom: 500 };

test("a card already in the room stays put", () => {
  assert.deepEqual(popupPan({ top: 100, left: 50, bottom: 300, right: 300 }, room), [0, 0]);
});

test("a card running under the panel is panned up by the overlap", () => {
  // Bethesda's card (the owner's screenshot): opened low, its bottom under the sheet.
  assert.deepEqual(popupPan({ top: 380, left: 50, bottom: 700, right: 300 }, room), [0, 200]);
});

test("a card off the top or a side comes back in", () => {
  assert.deepEqual(popupPan({ top: -40, left: -20, bottom: 100, right: 200 }, room), [-28, -56]);
  assert.deepEqual(popupPan({ top: 100, left: 200, bottom: 200, right: 420 }, room), [38, 0]);
});

test("a card taller than the room keeps its top, the name and buttons, in view", () => {
  assert.deepEqual(popupPan({ top: 300, left: 50, bottom: 900, right: 300 }, room), [0, 284]);
});

test("the station card is fitted when it opens and when its times come", () => {
  const rail = readFileSync(new URL("../railInteraction.ts", import.meta.url), "utf8");
  assert.match(rail, /fitCard\(popup\)[\s\S]*fillTimes\(times[^;]*;\s*fitCard\(popup\)/);
});

test("Go with no route: a station card's End here rides there from Go's start", () => {
  const rail = readFileSync(new URL("../railInteraction.ts", import.meta.url), "utf8");
  assert.match(rail, /if \(options\.endFromHere\?\.\(\) === true && options\.pointCount\(\) === 0\) roles\.push\("end"\);/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  // Said as a pressed destination is ("Destination set"): pressed = true.
  assert.match(app, /role === "end" && modeRef\.current === "go" && pointsRef\.current\.length === 0\) \{[\s\S]{0,120}goToRef\.current\(point, place\.name, true\)/);
  assert.match(app, /stationEndFromHere=\{mode === "go" && !onBike\}/);
});
