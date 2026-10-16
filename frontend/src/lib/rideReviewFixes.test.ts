// Ride mode fixes from the 2026-10-16 review (a11y-3 and the RIDE- findings), as the page wires them.
// The engines are tested in their own files; this holds the wiring, read as source.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const ride = source("../RideMode.tsx");

test("a11y-3: going off route, back on, or out of DC hands a dropped focus to Where am I? and closes the 311 menu", () => {
  const rescue = ride.slice(ride.indexOf("const shownBefore = useRef"), ride.indexOf("}, [ride.off, show311]);"));
  assert.ok(rescue.length > 100, "one rescue for both changes");
  assert.match(rescue, /if \(before\.off === ride\.off && before\.show311 === show311\) return;/);
  assert.match(rescue, /if \(!show311\) setMenu311\(false\);/);
  assert.match(rescue, /if \(!active \|\| active === document\.body \|\| !active\.isConnected\) whereRef\.current\?\.focus\(\);/);
  // After show311 is worked out, so it sees this render's value.
  assert.ok(ride.indexOf("const show311 = ride311Shown(") < ride.indexOf("const shownBefore = useRef"));
});
