// Featured routes photos: drawn again at most PHOTO_EDGE pixels on the longer side, never made larger (post/photos.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { PHOTO_EDGE, exifSpot, fitWithin } from "./photos.ts";

test("a phone's photo is drawn at most PHOTO_EDGE pixels on its longer side, keeping its shape", () => {
  assert.deepEqual(fitWithin(4032, 3024), { width: PHOTO_EDGE, height: 1200 });
  assert.deepEqual(fitWithin(3024, 4032), { width: 1200, height: PHOTO_EDGE });
});

test("a small photo is not made larger", () => {
  assert.deepEqual(fitWithin(800, 600), { width: 800, height: 600 });
  assert.deepEqual(fitWithin(1, 5000, 900), { width: 1, height: 900 });
});

// Where a photo was taken (the owner, 2026-11-07: "people want to know where they are taken"): read from the
// original file's Exif before it is drawn again, as core/route_posts.py exif_spot reads it.
const bytes = (b64: string): ArrayBuffer => {
  const raw = Buffer.from(b64, "base64");
  return raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
};

// route_posts.gps_segment(38.8893, -77.0502) between a JPEG's start and end.
const LOCATED =
  "/9j/4QCURXhpZgAATU0AKgAAAAgAAYglAAQAAAABAAAAGgAAAAAABQAAAAEAAAAEAgIAAAABAAIAAAACTgAAAAACAAUAAAADAAAAXAADAAIAAAACVwAAAAAEAAUAAAADAAAAdAAAAAAXLglIAJiWgAAAAAAAAAABAAAAAAAAAAEt7O1wAJiWgAAAAAAAAAABAAAAAAAAAAH/2Q==";

test("a photo's Exif says where it was taken, south and west as negative", () => {
  const spot = exifSpot(bytes(LOCATED));
  assert.ok(spot);
  assert.ok(Math.abs(spot[0] - 38.8893) < 1e-6 && Math.abs(spot[1] + 77.0502) < 1e-6);
});

test("a file without a readable position gives none", () => {
  assert.equal(exifSpot(bytes("iVBORw0KGgo=")), null);
  assert.equal(exifSpot(bytes(LOCATED).slice(0, 40)), null);
  assert.equal(exifSpot(new ArrayBuffer(0)), null);
});

// A camera's way, little-endian with degrees, minutes and seconds, south and east (tests/test_route_posts.py located_jpeg).
const CAMERA = "/9j/4QCIRXhpZgAASUkqAAgAAAABACWIBAABAAAAGgAAAAAAAAAEAAEAAgACAAAAUwAAAAIABQADAAAAUAAAAAMAAgACAAAARQAAAAQABQADAAAAaAAAAAAAAAAhAAAAAQAAADMAAAABAAAAWF8AAOgDAACXAAAAAQAAAAwAAAABAAAAKNcAAOgDAAD/4AAQSkZJRgABAQAAAQABAAD/4QAxRXhpZgAAR1BTTGF0aXR1ZGUgMzguODk3NyBHUFNMb25naXR1ZGUgLTc3LjAzNjX/4QA6aHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wLwA8eDp4bXBtZXRhPkRhdGVUaW1lT3JpZ2luYWz/4gAcSUNDX1BST0ZJTEUAIGlQaG9uZSBjYW1lcmH//gAOU2hvdCBhdCBob21l/9sAQwAAAQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyAhIiMkJSYnKCkqKywtLi8wMTIzNDU2Nzg5Ojs8PT4//8AACwgAAwAEAQERAP/aAAgBAQAAPwAS/wA0/9BW/9lQSwMEIGEgaGlkZGVuIGFyY2hpdmU=";

test("a camera's little-endian degrees, minutes and seconds are read too", () => {
  const spot = exifSpot(bytes(CAMERA));
  assert.ok(spot);
  assert.ok(Math.abs(spot[0] + 33.85678) < 1e-5 && Math.abs(spot[1] - 151.2153) < 1e-5);
});
