// A post's photos on its maps: a pin with a pop-out on the route's map, a thumbnail pointing to the spot on each
// section map it falls in (post/photoPins.ts; the owner, 2026-11-08).
import { test } from "node:test";
import assert from "node:assert/strict";
import { PHOTO_PIN_LABEL, besideOffset, photoPins, photosNear, pinLabel } from "./photoPins.ts";

const bridge = { url: "/routes/loop/photos/0123456789abcdef.jpg", lon: -77.2085, lat: 38.7689, alt: "A footbridge", caption: "Fall" };

test("only photos with a real spot and an address on this site are pinned", () => {
  assert.deepEqual(photoPins([bridge]), [bridge]);
  for (const bad of [
    { ...bridge, lon: Number.NaN },
    { ...bridge, lat: 91 },
    { ...bridge, url: "https://elsewhere.example/x.jpg" },
    { ...bridge, alt: 3 },
    null,
    "x",
  ]) {
    assert.deepEqual(photoPins([bad]), []);
  }
  assert.deepEqual(photoPins(undefined), []);
});

test("a section map shows the photos taken on or just beside its stretch", () => {
  const stretch = [
    [-77.21, 38.76],
    [-77.2, 38.78],
  ];
  const far = { ...bridge, lon: -77.05, lat: 38.89 };
  const beside = { ...bridge, lon: -77.2002, lat: 38.7805 };
  assert.deepEqual(photosNear(stretch, [bridge, far, beside]), [bridge, beside]);
  assert.deepEqual(photosNear([[-77.2, 38.7]], [bridge]), []);
});

test("a pin is read out as a photo with what it shows", () => {
  assert.equal(pinLabel(bridge), `${PHOTO_PIN_LABEL}: A footbridge`);
});

test("a thumbnail sits beside the route, square to it, on the side nearer the map's middle", () => {
  // A route running left to right along y = 100; the middle below it, then above it.
  const line = [[0, 100], [200, 100]] as const;
  const below = besideOffset([50, 100], line, [100, 300], 40);
  assert.ok(Math.abs(below.dx) < 1e-9 && Math.abs(below.dy - 40) < 1e-9);
  const above = besideOffset([50, 100], line, [100, 0], 40);
  assert.ok(Math.abs(above.dx) < 1e-9 && Math.abs(above.dy + 40) < 1e-9);
  // A route running up the screen: the thumbnail goes sideways, never along it.
  const side = besideOffset([100, 50], [[100, 0], [100, 200]], [0, 100], 40);
  assert.ok(Math.abs(side.dx + 40) < 1e-9 && Math.abs(side.dy) < 1e-9);
  // The nearest stretch decides, not the first one.
  const bend = besideOffset([300, 52], [[0, 0], [0, 50], [400, 50]], [300, 0], 30);
  assert.ok(Math.abs(bend.dx) < 1e-9 && Math.abs(bend.dy + 30) < 1e-9);
  // No stretch to go by: straight up.
  assert.deepEqual(besideOffset([5, 5], [[1, 1]], [0, 0], 30), { dx: 0, dy: -30 });
});
