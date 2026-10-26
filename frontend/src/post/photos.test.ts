// Featured routes photos: drawn again at most PHOTO_EDGE pixels on the longer side, never made larger (post/photos.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { PHOTO_EDGE, fitWithin } from "./photos.ts";

test("a phone's photo is drawn at most PHOTO_EDGE pixels on its longer side, keeping its shape", () => {
  assert.deepEqual(fitWithin(4032, 3024), { width: PHOTO_EDGE, height: 1200 });
  assert.deepEqual(fitWithin(3024, 4032), { width: 1200, height: PHOTO_EDGE });
});

test("a small photo is not made larger", () => {
  assert.deepEqual(fitWithin(800, 600), { width: 800, height: 600 });
  assert.deepEqual(fitWithin(1, 5000, 900), { width: 1, height: 900 });
});
