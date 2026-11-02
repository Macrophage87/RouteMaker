// A ride left going (Stephen 2026-10-24: "I clicked out of the app and lost the route. Allow a way to resume if that
// happens"): kept on the device at Start ride, offered at the next load, forgotten at End ride.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RouteResponse } from "./api.ts";
import type { Dials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import { ViaMarks } from "./pointKinds.ts";
import { leaderKey, newToken } from "./rideGroup.ts";
import { newRideSecret, withSecret } from "./rideSeal.ts";
import { asRideLink } from "./sharedRoutes.ts";
import { RESUME_MAX_MS, RIDE_RESUME_KEY, forgetLeftRide, keepLeftRide, keepLeftRideLeads, leftRide, resumedBroadcast } from "./rideResume.ts";

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
  assert.match(app, /if \(kept\) \{[\s\S]{0,300}?keepLeftRide\(\{ route, points: leg\.points, loop: leg\.loop, preset: leg\.preset, dials: rideDialsNow, fixed, destination, passOn, follows, leads: ledLink \}/);
  assert.match(app, /const endRide = useCallback\(\(after: EndedPlan, stats: RideStats\) => \{\s*const \{ start, mode: endedIn \} = rideNow\.current;\s*forgetLeftRide\(\);/);
  assert.match(app, /const \[leftAsk, setLeftAsk\] = useState\(\(\) => \(SHARED_RIDE && SHARED_LEAD \? null : leftRide\(VIA_MARKS, Date\.now\(\)\)\)\);/);
  assert.match(app, /<ResumeRideDialog\s+open=\{leftAsk !== null && !riding && !roaming\}/);
  assert.doesNotMatch(src("./rideResume.ts"), /fetch\(|origin/);
});

test("each new route of the ride is kept in its place, and the question holds the ride's own re-routes", () => {
  const ride = src("../RideMode.tsx");
  assert.match(ride, /if \(!trip && keepLeft\) keepLeftRide\(\{ route: found, points, loop: false, preset, dials: dialsRef\.current, fixed: fixedRef\.current \}, VIA_MARKS, Date\.now\(\)\);/);
  assert.match(ride, /const auto = !keepRef\.current && !fixedRef\.current && !restartOpen\.current;/);
  assert.match(ride, /!fixedRef\.current && !restartOpen\.current && !uturns\.current\.held && state\.goodFix && state\.goodFix\.accuracyM <= OFF_SURE_M && !replanHeld\(replannedFrom\.current, state\.goodFix\.point\)\) void replan/);
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

test("a ride following someone's broadcast keeps its link to pass on once resumed, through its re-routes; one's own has none", () => {
  const store = memory();
  const marks = new ViaMarks();
  const points: LonLat[] = [[-77, 38.9], [-77.01, 38.9]];
  const link = "https://x.test/s/abc#ride=1&lead=L&k=K";
  keepLeftRide({ route, points, loop: false, preset: "standard", dials, fixed: true, passOn: link, follows: true }, marks, 0, store);
  assert.equal(leftRide(marks, 0, store)?.passOn, link);
  assert.equal(leftRide(marks, 0, store)?.follows, true);
  // A re-route mid-ride (RideMode) says nothing of it: the one kept at Start goes on.
  keepLeftRide({ route, points: [[-77.002, 38.9], [-77.01, 38.9]], loop: false, preset: "standard", dials, fixed: true }, marks, 0, store);
  assert.equal(leftRide(marks, 0, store)?.passOn, link);
  assert.equal(leftRide(marks, 0, store)?.follows, true);
  // Following one whose link had no key: it follows, with nothing to pass on, through a re-route too.
  keepLeftRide({ route, points, loop: false, preset: "standard", dials, fixed: true, passOn: null, follows: true }, marks, 0, store);
  keepLeftRide({ route, points: [[-77.002, 38.9], [-77.01, 38.9]], loop: false, preset: "standard", dials, fixed: true }, marks, 0, store);
  assert.equal(leftRide(marks, 0, store)?.passOn, undefined);
  assert.equal(leftRide(marks, 0, store)?.follows, true);
  // The next ride, the rider's own, has neither.
  keepLeftRide({ route, points, loop: false, preset: "standard", dials, fixed: false, passOn: null, follows: false }, marks, 0, store);
  assert.equal(leftRide(marks, 0, store)?.passOn, undefined);
  assert.equal(leftRide(marks, 0, store)?.follows, undefined);
});

test("a resumed ride is on the broadcast it followed or led again: its id, leader and key read from the kept link", () => {
  const store = memory();
  const marks = new ViaMarks();
  const points: LonLat[] = [[-77, 38.9], [-77.01, 38.9]];
  const id = "a".repeat(32);
  const followed = `https://x.test/s/${id}#q=abc&route=${id}&ride=1&lead=${"B".repeat(21)}A&k=${"C".repeat(21)}A`;
  keepLeftRide({ route, points, loop: false, preset: "standard", dials, fixed: true, passOn: followed, follows: true }, marks, 0, store);
  const back = resumedBroadcast(leftRide(marks, 0, store)!);
  assert.equal(back?.id, id);
  assert.equal(back?.own, false);
  assert.equal(back?.secret, "C".repeat(21) + "A");
  assert.match(back?.lead ?? "", /^[0-9a-f]{32}$/);

  // The leader's own broadcast, started from the ride screen after Start: kept with the ride, through a re-route.
  keepLeftRide({ route, points, loop: false, preset: "standard", dials, fixed: false, passOn: null, follows: false, leads: null }, marks, 0, store);
  assert.equal(resumedBroadcast(leftRide(marks, 0, store)!), null);
  const led = followed.replace("x.test", "y.test");
  keepLeftRideLeads(led, store);
  keepLeftRide({ route, points: [[-77.002, 38.9], [-77.01, 38.9]], loop: false, preset: "standard", dials, fixed: false }, marks, 0, store);
  assert.equal(leftRide(marks, 0, store)?.leads, led);
  assert.deepEqual(resumedBroadcast(leftRide(marks, 0, store)!), { ...back, own: true });
  // The next ride is not that broadcast.
  keepLeftRide({ route, points, loop: false, preset: "standard", dials, fixed: false, passOn: null, follows: false }, marks, 0, store);
  assert.equal(leftRide(marks, 0, store)?.leads, undefined);

  // A link without its key, or its leader, rejoins nothing (nothing could be read or sent for it).
  assert.equal(resumedBroadcast({ follows: true, passOn: followed.replace(/&k=[^&]*/, "") }), null);
  assert.equal(resumedBroadcast({ follows: true, passOn: followed.replace(/&lead=[^&]*/, "") }), null);
  assert.equal(resumedBroadcast({ follows: false, passOn: followed }), null);
});

test("Resume puts the page back on the kept broadcast; Broadcast from the ride screen keeps its link with the ride", () => {
  const app = src("../App.tsx");
  const resume = app.slice(app.indexOf("const resumeLeft = () => {"), app.indexOf("const dropLeft = () => {"));
  assert.match(resume, /const on = resumedBroadcast\(left\);[\s\S]*setSharedOpen\(open\)/);
  assert.match(resume, /answer: left\.route/);
  assert.match(app, /if \(led && riding && rideStart\?\.kept\) \{\s*keepLeftRideLeads\(link\);\s*setRideStart\(\(before\) => \(before \? \{ \.\.\.before, leads: link \}/);
  // End ride then Undo keeps it too: the ride's start carries the link it leads.
  assert.match(app, /kept, passOn, follows, leads: ledLink, note,/);
  assert.match(app, /keepLeftRide\(\{[^}]*passOn, follows, leads: ledLink \}/);
});

test("a link Broadcast makes (its leader's key and the ride's key) reads back as the same leader and key on resume", async () => {
  const token = newToken();
  const key = await leaderKey(token);
  const secret = newRideSecret();
  const id = "d".repeat(32);
  const link = withSecret(asRideLink(`https://x.test/s/${id}#q=abc&route=${id}`, key), secret);
  assert.deepEqual(resumedBroadcast({ leads: link }), { id, lead: key, secret, own: true });
});

test("a ride link opened to follow joins that ride: no Resume question for a ride left going takes its place", () => {
  const app = src("../App.tsx");
  assert.match(app, /useState\(\(\) => \(SHARED_RIDE && SHARED_LEAD \? null : leftRide\(VIA_MARKS, Date\.now\(\)\)\)\)/);
});

test("the automatic re-plan while off route never starts from a rough fix", () => {
  const ride = src("../RideMode.tsx");
  assert.match(ride, /out\.state\.off && auto && !gate\.busy && fix\.accuracyM <= OFF_SURE_M/);
});
