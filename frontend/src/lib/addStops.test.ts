/** v0.7.0 "Keep adding stops by search": Plan's search adds stops, Go's route sheet has "Add a stop". */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { LonLat } from "./geo.ts";
import { ViaMarks, addStopWhereShortest, stopAddedSaid } from "./pointKinds.ts";
import { applyPlace, choiceInForce, placeEffect } from "./geocode.ts";

const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const p = (lon: number, lat = 38.9): LonLat => [lon, lat];

test("with a route, a searched place is a stop where it adds the least distance", () => {
  const start = p(-77.0);
  const end = p(-77.1);
  const choice = choiceInForce(null, 2, false);
  assert.equal(choice, "via");
  assert.equal(placeEffect(2, choice), "via");
  const near = p(-77.05, 38.901);
  assert.deepEqual(applyPlace([start, end], near, choice), [start, near, end]);
  // Go's "Add a stop" puts it in the same place, and says which stop it is, and that Undo removes it.
  const marks = new ViaMarks();
  const added = addStopWhereShortest([start, end], near);
  assert.deepEqual(added.points, [start, near, end]);
  assert.equal(stopAddedSaid(added.points, added.index, marks.isVia, false, "Union Market"), "Stop 1, Union Market, added. Undo removes it.");
});

test("each result row offers 'Make this the destination' as an option of its own", () => {
  const search = source("../PlaceSearch.tsx");
  assert.match(search, /export const MAKE_DESTINATION = "Make this the destination";/);
  assert.match(search, /const offersDestination = variant === "plan" && !loop && effect === "via";/);
  assert.match(search, /places\.flatMap\(\(place\) => \[place, \{ destination: place \}\]\)/);
  // An option in the listbox, reached by the arrows and said with its place.
  assert.match(search, /aria-label=\{`\$\{MAKE_DESTINATION\}: \$\{item\.destination\.name\}`\}/);
  assert.match(search, /onClick=\{\(\) => pick\(item\.destination, "end"\)\}/);
  // Go's field adds a stop.
  assert.match(search, /onPick\(place, as \?\? \(variant === "stop" \? "via" : single \? "end" : choice\)\);/);
});

test("Go's route sheet has one 'Add a stop' field above the route, with Best order, never during a ride", () => {
  const go = source("../app/Go.tsx");
  assert.match(go, /<PlaceSearch variant="stop"/);
  assert.match(go, /\{routeShown && addStop && size !== "peek" && addStop\}\s*\{routeShown && route\}/);
  assert.match(go, /\{orderShown && \(\s*<button[^>]*onClick=\{onBestOrder\}/);
  const app = source("../App.tsx");
  assert.match(app, /const goStops = mode === "go" && !riding && points\.length >= 2 && !twoPointsOnly\(preset\) && !isMassRide\(preset\);/);
  // One edit, so Undo removes it; the route follows at once, as every Go edit does.
  assert.match(app, /const added = addStopWhereShortest\(current, point, loop\);\s*setNotice\(null\);\s*commit\(added\.points\);/);
  // A chip's place (water, a restroom, food) is a stop once there is a route.
  assert.ok((app.match(/if \(mode === "go" && goStops\) \{/g) ?? []).length >= 2);
});
