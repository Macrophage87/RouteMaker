// A post's photos on its maps: a pin with a pop-out on the route's map, a thumbnail pointing to the spot on each
// section map it falls in (post/photoPins.ts; the owner, 2026-11-08).
import { test } from "node:test";
import assert from "node:assert/strict";
import { PHOTO_PIN_LABEL, photoPins, photosNear, pinLabel } from "./photoPins.ts";

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
