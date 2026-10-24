// The map's bounds with a phone's sheet over its bottom (lib/coveredConstrain.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { MIN_SHOWN_PX, constrainAbovePanel, shownCover, type ConstrainView } from "./coveredConstrain.ts";

const world = (z: number) => 512 * 2 ** z;
const yOf = (lat: number, z: number) => ((180 - (180 / Math.PI) * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))) / 360) * world(z);

// A phone, 400 x 800, with the sheet over the bottom 400 px.
const view = (covered: number): ConstrainView => ({ bounds: [-78, 38, -76, 40], minZoom: 7, maxZoom: 20, width: 400, height: 800, covered });

test("nothing covered: a centre inside the bounds stays put", () => {
  const out = constrainAbovePanel({ lng: -77, lat: 39 }, 12, view(0));
  assert.deepEqual(out, { center: { lng: -77, lat: 39 }, zoom: 12 });
});

test("nothing covered: the south edge stops at the map's bottom", () => {
  const z = 10;
  const out = constrainAbovePanel({ lng: -77, lat: 37 }, z, view(0));
  assert.ok(Math.abs(yOf(out.center.lat, z) + 400 - yOf(38, z)) < 1e-6);
});

test("with a sheet, the south edge can come up to the sheet's top", () => {
  const z = 10;
  const out = constrainAbovePanel({ lng: -77, lat: 37 }, z, view(400));
  // The map's centre is 400 px above its bottom and the sheet's top is 400 px above that bottom: the centre's own row.
  const sheetTop = yOf(out.center.lat, z);
  assert.ok(Math.abs(sheetTop - yOf(38, z)) < 1e-6);
  assert.ok(out.center.lat < constrainAbovePanel({ lng: -77, lat: 37 }, z, view(0)).center.lat);
});

test("with a sheet, the north edge still stops at the map's top", () => {
  const z = 10;
  const out = constrainAbovePanel({ lng: -77, lat: 41 }, z, view(400));
  assert.ok(Math.abs(yOf(out.center.lat, z) - 400 - yOf(40, z)) < 1e-6);
});

test("zoomed out past the bounds, the zoom goes in until the part above the sheet fits", () => {
  const out = constrainAbovePanel({ lng: -77, lat: 39 }, 7, view(400));
  const shownSpan = yOf(38, out.zoom) - yOf(40, out.zoom);
  const wideSpan = ((-76 - -78) / 360) * world(out.zoom);
  assert.ok(Math.abs(Math.max(400 / wideSpan, 400 / shownSpan) - 1) < 1e-9);
  // The bounds' middle is the middle of the part that shows.
  const mid = (yOf(38, out.zoom) + yOf(40, out.zoom)) / 2;
  if (Math.abs(shownSpan - 400) < 1e-6) assert.ok(Math.abs(yOf(out.center.lat, out.zoom) - 200 - mid) < 1e-6);
});

test("the cover never hides the whole map", () => {
  assert.equal(shownCover(900, 800), 800 - MIN_SHOWN_PX);
  assert.equal(shownCover(-5, 800), 0);
  assert.equal(shownCover(300, 800), 300);
});
