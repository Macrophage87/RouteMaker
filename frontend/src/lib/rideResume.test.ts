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
import { RESUME_MAX_MS, RIDE_RESUME_KEY, forgetLeftRide, keepLeftRide, keepLeftRideLeads, keepLeftRidePast, leftRide, leftRidePast, resumedBroadcast } from "./rideResume.ts";

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
  assert.match(app, /if \(kept\) \{[\s\S]{0,500}?keepLeftRide\(\{ route, \.\.\.whole, dials: rideDialsNow, fixed, destination, passOn, follows, leads: ledLink, stopsLeft: tripStopsLeft\.current \}/);
  assert.match(app, /const endRide = useCallback\(\(after: EndedPlan, stats: RideStats, docked\?: RebalanceDocked \| null\) => \{\s*const \{ start, mode: endedIn \} = rideNow\.current;[\s\S]{0,200}?const past = start\?\.whole \? leftRidePast\(\) : null;\s*forgetLeftRide\(\);/);
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
  // A Bikeshare or transit trip is kept whole, Ride the rest too (Stephen 2026-11-04); a detour from Roam is not.
  assert.match(app, /const kept = !rest\?\.roam;/);
  // Its loop as rideLegOf was given it (a walk_in loop or run stays a loop).
  assert.match(app, /const whole = leg\.trip \? \{ points: ridePoints, loop: rest \? false : routedLoop, preset: route\.preset, wholeTrip: true \} : \{ points: leg\.points, loop: leg\.loop, preset: leg\.preset \};/);
  assert.match(app, /keepLeft=\{rideStart\.kept === true\}/);
  // Undo keeps it whole again with what End ride read of it (the walk or train followed, the stops left), never the
  // progress an earlier Resume started from.
  assert.match(app, /if \(ended\.start\.kept\) keepLeftRide\(\{ \.\.\.\(ended\.start\.whole \? \{ \.\.\.ended\.start, \.\.\.ended\.start\.whole \} : ended\.start\), past: ended\.past, stopsLeft: ended\.stopsLeft \}, VIA_MARKS, Date\.now\(\)\);/);
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
  assert.match(app, /keepLeftRide\(\{[^}]*passOn, follows, leads: ledLink, stopsLeft: tripStopsLeft\.current \}/);
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

// Stephen 2026-11-04: on the train, switching apps "terminated the route without offering a resume".
test("a transit trip is kept whole, with the walk or train it is following, and Resume carries on from there", () => {
  const store = memory();
  const marks = new ViaMarks();
  const points: LonLat[] = [[-77, 38.9], [-77.01, 38.9]];
  // A plain ride says nothing of a trip, and a past written for it is dropped.
  keepLeftRide({ route, points, loop: false, preset: "standard", dials, fixed: false }, marks, 0, store);
  keepLeftRidePast({ index: 1, since: 5, walk: null, board: null }, store);
  assert.equal(leftRide(marks, 0, store)?.wholeTrip, undefined);
  assert.equal(leftRide(marks, 0, store)?.past, undefined);
  // A trip: kept whole, then the train it is on.
  keepLeftRide({ route, points, loop: false, preset: "transit", dials, fixed: false, wholeTrip: true }, marks, 0, store);
  assert.equal(leftRide(marks, 0, store)?.wholeTrip, true);
  assert.equal(leftRide(marks, 0, store)?.past, null);
  const board = { since: 10, boardedAt: 20, at: 3, fixAt: 30, saidNext: false, saidOff: false, done: false };
  keepLeftRidePast({ index: 1, since: 10, walk: null, board }, store);
  assert.deepEqual(leftRide(marks, 0, store)?.past, { index: 1, since: 10, walk: null, board });
  // Kept again at Resume, with where it was.
  const left = leftRide(marks, 0, store)!;
  keepLeftRide(left, marks, 0, store);
  assert.equal(leftRide(marks, 0, store)?.past?.board?.at, 3);
  // Unreadable progress: Resume starts the leg again rather than failing.
  const raw = JSON.parse(store.getItem(RIDE_RESUME_KEY)!);
  store.setItem(RIDE_RESUME_KEY, JSON.stringify({ ...raw, past: { index: "x" } }));
  assert.equal(leftRide(marks, 0, store)?.past, null);
});

test("Resume of a trip works its leg out again and carries on past the line; the ride screen starts there", () => {
  const app = src("../App.tsx");
  assert.match(app, /const leg = left\.wholeTrip \? rideLegOf\(left\.route, left\.points, left\.loop\) : null;/);
  assert.match(app, /resumedPast=\{rideStart\.past \?\? null\}/);
  const ride = src("../RideMode.tsx");
  assert.match(ride, /useState<RideState>\(\(\) => \(resumedPast \? \{ \.\.\.startState\(\), arrived: true \} : startState\(\)\)\)/);
  assert.match(ride, /const onwardRef = useRef<OnwardState \| null>\(resumedPast\);/);
  assert.match(ride, /if \(onwardRef\.current\) keepLeftRidePast\(onwardRef\.current\);\s*\}, \[pastKey\]\);/);
});

test("a run loop planned from its start alone is kept with its one point and offered for Resume", () => {
  const store = memory();
  const marks = new ViaMarks();
  keepLeftRide({ route, points: [[-77, 38.9]], loop: true, preset: "run", dials, fixed: false, wholeTrip: true }, marks, 0, store);
  const left = leftRide(marks, 60_000, store);
  assert.ok(left);
  assert.deepEqual(left.points, [[-77, 38.9]]);
  assert.equal(left.loop, true);
  // A one-point ride that is no loop says nothing to resume.
  keepLeftRide({ route, points: [[-77, 38.9]], loop: false, preset: "standard", dials, fixed: false }, marks, 0, store);
  assert.equal(leftRide(marks, 0, store), null);
});

test("a trip with stops keeps the stops after it, marked as they were, so Resume still offers Start the next leg", () => {
  const store = memory();
  const marks = new ViaMarks();
  const stopsLeft = { preset: "transit" as const, points: [marks.named([-77.01, 38.9], "Union Market"), marks.via([-77.02, 38.91]), [-77.03, 38.92] as LonLat] };
  keepLeftRide({ route, points: [[-77, 38.9], [-77.01, 38.9]], loop: false, preset: "transit", dials, fixed: false, wholeTrip: true, stopsLeft }, marks, 0, store);
  const back = new ViaMarks();
  const left = leftRide(back, 0, store)!;
  assert.equal(left.stopsLeft?.preset, "transit");
  assert.deepEqual(left.stopsLeft?.points, [[-77.01, 38.9], [-77.02, 38.91], [-77.03, 38.92]]);
  assert.equal(back.nameOf(left.stopsLeft!.points[0]), "Union Market");
  assert.equal(back.isVia(left.stopsLeft!.points[1]), true);
  // Kept again at Resume with them; a trip with none has none.
  keepLeftRide(left, back, 0, store);
  assert.equal(leftRide(back, 0, store)?.stopsLeft?.points.length, 3);
  keepLeftRide({ route, points: [[-77, 38.9], [-77.01, 38.9]], loop: false, preset: "transit", dials, fixed: false, wholeTrip: true }, marks, 0, store);
  assert.equal(leftRide(marks, 0, store)?.stopsLeft, undefined);
});

test("End ride reads the walk or train a trip was following, so Undo carries on from it; a plain ride has none", () => {
  const store = memory();
  const marks = new ViaMarks();
  const points: LonLat[] = [[-77, 38.9], [-77.01, 38.9]];
  keepLeftRide({ route, points, loop: false, preset: "transit", dials, fixed: false, wholeTrip: true }, marks, 0, store);
  assert.equal(leftRidePast(store), null);
  const board = { since: 10, boardedAt: 20, at: 3, fixAt: 30, saidNext: false, saidOff: false, done: false };
  keepLeftRidePast({ index: 1, since: 10, walk: null, board }, store);
  assert.deepEqual(leftRidePast(store), { index: 1, since: 10, walk: null, board });
  keepLeftRide({ route, points, loop: false, preset: "standard", dials, fixed: false }, marks, 0, store);
  assert.equal(leftRidePast(store), null);
  assert.equal(leftRidePast(memory()), null);
});

test("Undo after End ride past a trip's line rides on with the train or walk; Resume checks the trip again and keeps its stops", () => {
  const app = src("../App.tsx");
  const end = app.slice(app.indexOf("const endRide = useCallback("), app.indexOf("const undoEndRide = () => {"));
  assert.match(end, /const past = start\?\.whole \? leftRidePast\(\) : null;\s*forgetLeftRide\(\);/);
  const undo = app.slice(app.indexOf("const undoEndRide = () => {"), app.indexOf("const finishRide = () => {"));
  assert.match(undo, /setRideStart\(\{ \.\.\.ended\.start, past: ended\.past \}\);/);
  assert.doesNotMatch(undo, /past: null/);
  const resume = app.slice(app.indexOf("const resumeLeft = () => {"), app.indexOf("const dropLeft = () => {"));
  assert.match(resume, /tripStopsLeft\.current = left\.stopsLeft \?\? null;\s*tripCheck\.current = checkTripOf\(left\.route, left\.points\);/);
  assert.match(app, /tripCheck\.current = checkTripOf\(route, ridePoints\);/);
});

test("back within minutes of putting the page away, Resume carries on without asking which stops are done (Stephen, 2026-11-07)", async () => {
  const { RESUME_QUIET_MS, RIDE_RESUME_KEY, resumesQuietly, seeLeftRide } = await import("./rideResume.ts");
  const kept = new Map<string, string>();
  const store = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v), removeItem: (k: string) => void kept.delete(k) };
  // Nothing kept: nothing to mark.
  seeLeftRide(1000, null, store);
  assert.equal(kept.size, 0);
  kept.set(RIDE_RESUME_KEY, JSON.stringify({ v: 1, at: 0 }));
  // The figures go with it (switching off "resets progress"), without the last fix and its line.
  const stats = { startedAt: 1, distanceM: 4200, movingMs: 900_000, climbM: 30, stressM: {}, elevation: [], last: { point: [-77, 38.9] as [number, number], at: 2, accuracyM: 5, progressM: 10, model: null } };
  seeLeftRide(5000, stats, store);
  const written = JSON.parse(kept.get(RIDE_RESUME_KEY)!);
  assert.equal(written.seen, 5000);
  assert.equal(written.stats.distanceM, 4200);
  assert.equal(written.stats.last, null);
  assert.equal(resumesQuietly({ seen: 5000 }, 5000 + RESUME_QUIET_MS), true);
  assert.equal(resumesQuietly({ seen: 5000 }, 5001 + RESUME_QUIET_MS), false);
  assert.equal(resumesQuietly({}, 5000), false);
  assert.equal(resumesQuietly({ seen: 9000 }, 5000), false);
  const ride = src("../RideMode.tsx");
  assert.match(ride, /if \(document\.visibilityState === "hidden" && !ended\.current\) seeLeftRide\(Date\.now\(\), statsRef\.current\);/);
  assert.match(src("../App.tsx"), /const quiet = resumesQuietly\(left, Date\.now\(\)\);\s*\/\/[^\n]*\n\s*setResumeStats\(quiet \? \(left\.stats \?\? null\) : null\);/);
});
