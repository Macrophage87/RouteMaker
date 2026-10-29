// A ride left going (Stephen 2026-10-24: "I clicked out of the app and lost the route. Allow a way to resume if that
// happens"): kept on the device at Start ride, offered at the next load, forgotten at End ride.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RouteResponse } from "./api.ts";
import type { Dials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import { ViaMarks } from "./pointKinds.ts";
import { RESUME_MAX_MS, RIDE_RESUME_KEY, forgetLeftRide, keepLeftRide, leftRide } from "./rideResume.ts";

function memory() {
  const items = new Map<string, string>();
  return {
    items,
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
  };
}
const route = { geometry: { type: "LineString", coordinates: [[-77, 38.9], [-77.01, 38.9]] }, distance_m: 900 } as unknown as RouteResponse;
const dials = { stress: 40 } as unknown as Dials;
const src = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("a ride kept at Start comes back with its stops, via points, names and drawn legs; End forgets it", () => {
  const store = memory();
  const marks = new ViaMarks();
  const points: LonLat[] = [[-77, 38.9], marks.named([-77.005, 38.9], "Union Market"), marks.via([-77.007, 38.9]), marks.drawn([-77.01, 38.9])];
  keepLeftRide({ route, points, loop: false, preset: "standard", dials, fixed: false }, marks, 1000, store);
  const back = new ViaMarks();
  const left = leftRide(back, 1000 + 60_000, store);
  assert.ok(left);
  assert.deepEqual(left.points, points.map((p) => [p[0], p[1]]));
  assert.notEqual(left.points[1], points[1], "fresh pairs, marked again");
  assert.equal(back.nameOf(left.points[1]), "Union Market");
  assert.equal(back.isVia(left.points[2]), true);
  assert.equal(back.isVia(left.points[1]), false);
  assert.equal(back.isDrawn(left.points[3]), true);
  assert.equal(left.preset, "standard");
  assert.deepEqual(left.route, route);
  forgetLeftRide(store);
  assert.equal(leftRide(back, 2000, store), null);
});

test("a ride left too long ago, or unreadable, is not offered and is forgotten; storage that throws starts nothing", () => {
  const store = memory();
  const marks = new ViaMarks();
  keepLeftRide({ route, points: [[-77, 38.9], [-77.01, 38.9]], loop: true, preset: "standard", dials, fixed: true }, marks, 0, store);
  assert.equal(leftRide(marks, RESUME_MAX_MS, store)?.loop, true);
  assert.equal(leftRide(marks, RESUME_MAX_MS + 1, store), null);
  assert.equal(store.items.has(RIDE_RESUME_KEY), false);
  store.setItem(RIDE_RESUME_KEY, "{not json");
  assert.equal(leftRide(marks, 0, store), null);
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("full"); }, removeItem: () => { throw new Error("blocked"); } };
  assert.doesNotThrow(() => keepLeftRide({ route, points: [[-77, 38.9], [-77.01, 38.9]], loop: false, preset: "standard", dials, fixed: false }, marks, 0, broken));
  assert.equal(leftRide(marks, 0, broken), null);
});

test("the page keeps the ride at Start, forgets it at End, and asks at load; nothing goes to the server", () => {
  const app = src("../App.tsx");
  assert.match(app, /if \(kept\) \{[\s\S]{0,300}?keepLeftRide\(\{ route, points: leg\.points, loop: leg\.loop, preset: leg\.preset, dials: rideDialsNow, fixed, destination \}/);
  assert.match(app, /const endRide = useCallback\(\(after: EndedPlan, stats: RideStats\) => \{\s*const \{ start, mode: endedIn \} = rideNow\.current;\s*forgetLeftRide\(\);/);
  assert.match(app, /const \[leftAsk, setLeftAsk\] = useState\(\(\) => leftRide\(VIA_MARKS, Date\.now\(\)\)\);/);
  assert.match(app, /<ResumeRideDialog\s+open=\{leftAsk !== null && !riding && !roaming\}/);
  assert.doesNotMatch(src("./rideResume.ts"), /fetch\(|origin/);
});

test("each new route of the ride is kept in its place, and the question holds the ride's own re-routes", () => {
  const ride = src("../RideMode.tsx");
  assert.match(ride, /if \(!trip && keepLeft\) keepLeftRide\(\{ route: found, points, loop: false, preset, dials: dialsRef\.current, fixed: fixedRef\.current \}, VIA_MARKS, Date\.now\(\)\);/);
  assert.match(ride, /const auto = !keepRef\.current && !fixedRef\.current && !restartOpen\.current;/);
  assert.match(ride, /!fixedRef\.current && !restartOpen\.current && !uturns\.current\.held && state\.goodFix\) void replan/);
  const app = src("../App.tsx");
  assert.match(app, /const kept = !rest && !leg\.trip;/);
  assert.match(app, /keepLeft=\{rideStart\.kept === true\}/);
  assert.match(app, /if \(ended\.start\.kept\) keepLeftRide\(ended\.start, VIA_MARKS, Date\.now\(\)\);/);
});

test("the ride's destination is kept with it, through its re-routes, to name it in the question (the UI review, 2026-10-28)", () => {
  const store = memory();
  const marks = new ViaMarks();
  const points: LonLat[] = [[-77, 38.9], [-77.01, 38.9]];
  keepLeftRide({ route, points, loop: false, preset: "standard", dials, fixed: false, destination: "Union Station" }, marks, 0, store);
  assert.equal(leftRide(marks, 0, store)?.destination, "Union Station");
  // A re-route from where the rider is, to the same end, keeps the name; one to elsewhere, or a loop, has none.
  keepLeftRide({ route, points: [[-77.002, 38.9], [-77.01, 38.9]], loop: false, preset: "standard", dials, fixed: false }, marks, 0, store);
  assert.equal(leftRide(marks, 0, store)?.destination, "Union Station");
  keepLeftRide({ route, points: [[-77.002, 38.9], [-77.02, 38.9]], loop: false, preset: "standard", dials, fixed: false }, marks, 0, store);
  assert.equal(leftRide(marks, 0, store)?.destination, undefined);
  keepLeftRide({ route, points, loop: true, preset: "standard", dials, fixed: false, destination: "Home" }, marks, 0, store);
  assert.equal(leftRide(marks, 0, store)?.destination, undefined);
});
