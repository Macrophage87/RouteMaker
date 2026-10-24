// The map's bounds with a phone's sheet over its bottom (lib/coveredConstrain.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { MIN_SHOWN_PX, constrainAbovePanel, shownCover, turned, type ConstrainView } from "./coveredConstrain.ts";

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

test("zoomed out past the bounds, the zoom goes in until the part above the sheet fits, centred on it", () => {
  // A wide, short area (about 730 x 235 px at zoom 7), so its height is what does not fit above the sheet.
  const wide: ConstrainView = { ...view(400), bounds: [-79, 38.5, -75, 39.5] };
  const out = constrainAbovePanel({ lng: -77, lat: 39 }, 7, wide);
  assert.ok(out.zoom > 7);
  assert.ok(Math.abs(yOf(38.5, out.zoom) - yOf(39.5, out.zoom) - 400) < 1e-6);
  // The bounds' middle is the middle of the part that shows, 200 px above the map's centre.
  const mid = (yOf(38.5, out.zoom) + yOf(39.5, out.zoom)) / 2;
  assert.ok(Math.abs(yOf(out.center.lat, out.zoom) - 200 - mid) < 1e-6);
});

test("padding moves the centre point: a frame round a junction shows no more past the edge", () => {
  const z = 10;
  // The frame Plan uses on a phone: the centre point sits in the middle of the strip above the sheet.
  const padded: ConstrainView = { ...view(400), padding: { top: 40, bottom: 490, left: 30, right: 30 } };
  const out = constrainAbovePanel({ lng: -77, lat: 37 }, z, padded);
  // The centre point is at y 175; the sheet's top (400) is 225 px below it and must not pass the south edge.
  assert.ok(Math.abs(yOf(out.center.lat, z) + 225 - yOf(38, z)) < 1e-6);
});

test("a turned map gets MapLibre's own check, the whole box inside", () => {
  const z = 10;
  const out = constrainAbovePanel({ lng: -77, lat: 37 }, z, { ...view(400), bearing: 180, padding: { top: 0, bottom: 300, left: 0, right: 0 } });
  assert.deepEqual(out, constrainAbovePanel({ lng: -77, lat: 37 }, z, view(0)));
  assert.equal(turned(-360), false);
  assert.equal(turned(359.995), false);
  assert.equal(turned(90), true);
});

test("the cover never hides the whole map", () => {
  assert.equal(shownCover(900, 800), 800 - MIN_SHOWN_PX);
  assert.equal(shownCover(-5, 800), 0);
  assert.equal(shownCover(300, 800), 300);
});
