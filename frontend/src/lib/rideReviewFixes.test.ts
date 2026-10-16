// Ride mode fixes from the 2026-10-16 review (a11y-3 and the RIDE- findings), as the page wires them.
// The engines are tested in their own files; this holds the wiring, read as source.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { REPLAN_FINDING, REPLAN_STILL_WAITING } from "./navigate.ts";

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

test("RIDE-1: hidden in the installed app, the ride's map so far goes to the last ride, and the ride keeps going", () => {
  assert.match(ride, /if \(document\.visibilityState === "hidden" && !ended\.current\) void copyCorridor\(lastRideAdopter\(\)\);/);
  const hook = ride.slice(ride.indexOf("const onHide = () =>") - 200, ride.indexOf("const onHide = () =>"));
  assert.match(hook, /if \(!handsOn\.current\) return;/, "the installed app only, as End ride's hand-on");
});

test("RIDE-5: Re-plan from here answers every press: finding, still waiting, or no fix yet", () => {
  assert.equal(REPLAN_FINDING, "Finding a new way from here.");
  assert.equal(REPLAN_STILL_WAITING, "Still waiting for the last re-plan.");
  const press = ride.slice(ride.indexOf("const replanNow = () => {"), ride.indexOf("void replan(here);\n  };"));
  assert.match(press, /if \(prefsRef\.current\.output === "neither"\) setPolite/);
  assert.match(press, /if \(replanning \|\| gate\.busy\) \{\s*answer\(REPLAN_STILL_WAITING\);\s*return;/);
  assert.match(press, /if \(!here\) \{\s*answer\(NO_FIX_YET\);\s*return;/);
  assert.match(press, /answer\(REPLAN_FINDING\);\s*$/);
  assert.doesNotMatch(press, /if \(replanning\) return;/, "no silent press");
});
