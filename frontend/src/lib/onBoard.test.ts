// Stop by stop on transit (Stephen, 2026-11-02): the stops followed by any fix that places the rider, a Wi-Fi fix
// underground too, else by the timetable; "Next stop" one before the rider's, then "Get off here".
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { TransitStep } from "./api.ts";
import type { LonLat } from "./geo.ts";
import type { RideFix } from "./navigate.ts";
import { STALE_MS, boardingGroups, lineColour, onBoardFeatures, onBoardPath, onBoardSecondsLeft, laterDepartureText, lineBadge, liveForBoarding, liveNextText, nextDepartureText, onBoardLeg, onBoardRows, onBoardStart, onBoardStep, stopsLeftText, type OnBoardState } from "./onBoard.ts";
import { onwardOf, onwardStart, onwardStep, onwardWhere } from "./onward.ts";

const M_PER_DEG = 111_195;
function north(m: number): LonLat {
  return [-77.0, 38.9 + m / M_PER_DEG];
}
function fix(point: LonLat, accuracyM: number, at: number): RideFix {
  return { point, accuracyM, speedMs: null, headingDeg: null, at };
}

// Takoma to Union Station: five stops 1.2 km apart, 2 min between them.
const NAMES = ["Takoma", "Fort Totten", "Brookland-CUA", "Rhode Island Ave", "NoMa-Gallaudet U", "Union Station"];
const STEP: TransitStep = {
  mode: "metro",
  text: "Board the Red Line toward Shady Grove (every 8 min, scheduled; about 4 min wait); ride 10 min to Union Station.",
  seconds: 600,
  wait_s: 240,
  to: "Union Station",
  lines: ["Red Line"],
  system: "Metro",
  with_bike: true,
  route_line: false,
  coordinates: NAMES.map((_, i) => north(i * 1200)),
  stops: NAMES.map((name, i) => ({ name, point: north(i * 1200), after_s: i * 120 })),
  toward: "Shady Grove",
};
const LEG = onBoardLeg(STEP)!;

test("a transit step with its stops is one to follow; one without (an older API) is not", () => {
  assert.equal(LEG.line, "Red Line");
  assert.equal(LEG.toward, "Shady Grove");
  assert.equal(LEG.bus, false);
  assert.equal(onBoardLeg({ ...STEP, stops: null }), null);
});

test("on board by GPS: passing stops, 'Next stop' one before, 'Get off here' at it, never twice", () => {
  const t0 = 1_000_000;
  let s: OnBoardState = onBoardStart(t0);
  const said: string[] = [];
  const go = (m: number, acc: number, dt: number) => {
    const out = onBoardStep(LEG, s, t0 + dt, fix(north(m), acc, t0 + dt));
    s = out.state;
    said.push(...out.said);
  };
  // Waiting on the platform: not on board.
  go(30, 20, 10_000);
  assert.equal(s.boardedAt, null);
  assert.equal(stopsLeftText(LEG, s), "5 stops left");
  // Wi-Fi fixes at Fort Totten then Brookland, 300 m out: on board once two agree.
  go(1200, 300, 300_000);
  assert.equal(s.boardedAt, null);
  go(2400, 300, 400_000);
  assert.ok(s.boardedAt !== null);
  assert.equal(s.at, 1);
  go(2450, 300, 420_000);
  assert.equal(s.at, 2);
  assert.deepEqual(said, []);
  assert.deepEqual(
    onBoardRows(LEG, s).map((r) => [r.name, r.next, r.off]).slice(2),
    [["Brookland-CUA", false, false], ["Rhode Island Ave", true, false], ["NoMa-Gallaudet U", false, false], ["Union Station", false, true]],
  );
  go(3600, 100, 500_000);
  go(4800, 100, 600_000);
  assert.deepEqual(said, ["Next stop: Union Station. Get off there."]);
  go(4850, 100, 610_000);
  assert.equal(said.length, 1);
  go(6000, 100, 700_000);
  assert.deepEqual(said, ["Next stop: Union Station. Get off there.", "Get off here: Union Station."]);
  assert.equal(s.done, true);
  // A fix back down the line (a rough one) never moves the stops back.
  const after = onBoardStep(LEG, { ...s, done: false, at: 5 }, t0 + 710_000, fix(north(1200), 400, t0 + 710_000));
  assert.equal(after.state.at, 5);
});

test("one rough fix far down the line is not taken: no 'Get off' from a stray Wi-Fi fix (review of #886)", () => {
  let s = { ...onBoardStart(0), boardedAt: 0, at: 1, fixAt: 60_000 };
  // 20 s after the last fix the train can be at most about 1.6 km on; a fix 4 km ahead is outside the window.
  const out = onBoardStep(LEG, s, 80_000, fix(north(5200), 450, 80_000));
  assert.equal(out.state.at, 1);
  assert.deepEqual(out.said, []);
  // One rough fix in the window moves the stops on, but never to the last two alone.
  s = onBoardStep(LEG, s, 200_000, fix(north(4800), 300, 200_000)).state;
  assert.equal(s.at, 3);
});

test("stops a block apart: boarded at the next stop, and a bus's button is said before the stop before the rider's is left", () => {
  const close = onBoardLeg({ ...STEP, mode: "bus", lines: ["B10"], stops: [0, 300, 600, 900].map((m, i) => ({ name: `S${i}`, point: north(m), after_s: i * 60 })) })!;
  let s = onBoardStart(0);
  const said: string[] = [];
  for (const [m, at] of [[20, 10_000], [310, 70_000], [560, 130_000]] as const) {
    const out = onBoardStep(close, s, at, fix(north(m), 10, at));
    s = out.state;
    said.push(...out.said);
  }
  assert.ok(s.boardedAt !== null);
  assert.equal(s.at, 2);
  assert.deepEqual(said, ["Next stop: S3. Press the stop button to get off there."]);
  // Two stops 350 m apart: a good fix at the second ends the ride.
  const two = onBoardLeg({ ...STEP, stops: [0, 350].map((m, i) => ({ name: `T${i}`, point: north(m), after_s: i * 60 })) })!;
  let t2 = onBoardStart(0);
  t2 = onBoardStep(two, t2, 10_000, fix(north(150), 10, 10_000)).state;
  assert.equal(t2.done, false);
  const end = onBoardStep(two, t2, 60_000, fix(north(340), 10, 60_000));
  assert.deepEqual(end.said, ["Get off here: T1."]);
});
test("a fix too rough or off the line says nothing; a bus says to press the stop button", () => {
  const s = onBoardStart(0);
  assert.equal(onBoardStep(LEG, s, 1000, fix(north(3000), 900, 1000)).state.fixAt, null);
  assert.equal(onBoardStep(LEG, s, 1000, fix([-76.9, 38.9], 30, 1000)).state.fixAt, null);
  const bus = onBoardLeg({ ...STEP, mode: "bus", lines: ["B10"] })!;
  const out = onBoardStep(bus, { ...s, boardedAt: 0, at: 3 }, 5000, fix(north(4800), 50, 5000));
  assert.deepEqual(out.said, ["Next stop: Union Station. Press the stop button to get off there."]);
});

test("no fix underground: the timetable, from the planned wait, places the train and says so", () => {
  let s = onBoardStart(0);
  // Nothing for a while: still waiting (the planned wait and STALE_MS have not run out).
  s = onBoardStep(LEG, s, 200_000).state;
  assert.equal(s.boardedAt, null);
  // Past the wait and STALE_MS: boarded at the end of the planned wait (240 s), stops by their scheduled seconds.
  s = onBoardStep(LEG, s, 240_000 + STALE_MS + 1).state;
  assert.equal(s.boardedAt, 240_000);
  const out1 = onBoardStep(LEG, s, 240_000 + 4 * 120_000 + 1000);
  assert.equal(out1.state.at, 4);
  assert.deepEqual(out1.said, ["Next stop should be Union Station, by the timetable. Get off there."]);
  const out2 = onBoardStep(LEG, out1.state, 240_000 + 5 * 120_000 + 1000);
  assert.deepEqual(out2.said, ["Union Station should be about now, by the timetable. Get off there."]);
  assert.equal(out2.state.done, true);
});

test("seen on the platform after the planned wait (a train missed): the timetable counts from then (review of #886)", () => {
  let s = onBoardStart(0);
  s = onBoardStep(LEG, s, 600_000, fix(north(20), 20, 600_000)).state;
  s = onBoardStep(LEG, s, 600_000 + STALE_MS + 1).state;
  assert.equal(s.boardedAt, 600_000);
  assert.equal(onBoardStep(LEG, s, 600_000 + 300_000).state.at, 2);
});

test("after the line: the walk to the station, the train, the walk on; a ride after it stops the list", () => {
  const walk = (coordinates: LonLat[]): TransitStep => ({ mode: "walk", text: "Walk 3 min.", seconds: 180, wait_s: 0, to: null, lines: [], with_bike: false, route_line: false, coordinates, turns: [] });
  const steps: TransitStep[] = [
    { ...walk([]), mode: "bikeshare", route_line: true },
    walk([north(-300), north(0)]),
    { ...walk([]), mode: "enter" },
    STEP,
    { ...walk([]), mode: "exit" },
    walk([north(6000), north(6300)]),
    { ...walk([north(6300), north(6400)]), mode: "ride" },
    walk([north(6400), north(6500)]),
  ];
  const parts = onwardOf(steps, 0);
  assert.deepEqual(parts.map((p) => p.kind), ["walk", "transit", "walk"]);
  // The walk to the station ends at the station; the train then begins.
  let s = onwardStart(parts, 0);
  s = onwardStep(parts, s, 1000, fix(north(-300), 5, 1000), "full").state;
  s = onwardStep(parts, s, 4000, fix(north(-10), 5, 4000), "full").state;
  assert.equal(s.index, 1);
  assert.ok(s.board);
});

test("a walk not seen to end (no GPS on the way down) hands over after its planned time; a rough fix at the stop does too", () => {
  const walk = (coordinates: LonLat[]): TransitStep => ({ mode: "walk", text: "Walk 3 min.", seconds: 180, wait_s: 0, to: null, lines: [], with_bike: false, route_line: false, coordinates, turns: [] });
  const parts = onwardOf([{ ...walk([]), mode: "bikeshare", route_line: true }, walk([north(-300), north(0)]), STEP], 0);
  let s = onwardStart(parts, 0);
  s = onwardStep(parts, s, 1000, fix(north(-300), 5, 1000), "full").state;
  assert.equal(onwardStep(parts, s, 200_000, null, "full").state.index, 0);
  assert.equal(onwardStep(parts, s, (180 * 1.5 + 180) * 1000 + 1, null, "full").state.index, 1);
  assert.equal(onwardStep(parts, s, 60_000, fix(north(30), 250, 60_000), "full").state.index, 1);
});

test("waiting to board, the card's next departure: a timed one's minutes, a frequent one's interval (Stephen, 2026-11-03: \"7 min works fine\")", () => {
  const departs_at = "2026-11-03T18:27:00-05:00";
  const at = Date.parse(departs_at);
  const timed = { departs: "6:27 pm", departs_at };
  assert.equal(nextDepartureText({ everyMin: null }, timed, at - 12 * 60_000), "12 min");
  assert.equal(nextDepartureText({ everyMin: null }, timed, at - 30_000), "1 min");
  // An hour or more off: its time.
  assert.equal(nextDepartureText({ everyMin: null }, timed, at - 75 * 60_000), "6:27 pm");
  assert.equal(nextDepartureText({ everyMin: null }, timed, at + 1000), "Now");
  // Long past: the time alone, never "Now" for ever.
  assert.equal(nextDepartureText({ everyMin: null }, timed, at + 5 * 60_000), "6:27 pm");
  assert.equal(nextDepartureText({ everyMin: 5 }, null, at), "every 5 min");
  // The plan's countdown is another step's: the step's own time.
  assert.equal(nextDepartureText({ everyMin: null, departs: "7:42 am" }, null, at), "7:42 am");
  assert.equal(nextDepartureText({ everyMin: null }, null, at), null);
  // The one after it, in case the rider can't make it.
  assert.equal(laterDepartureText({ next: "7:15 pm", next_at: "2026-11-03T19:15:00-05:00" }, at), "48 min");
  assert.equal(laterDepartureText({ next: null, next_at: null }, at), null);
  assert.equal(laterDepartureText(null, at), null);
});

test("the trains that will do, grouped by where they are signed to, with their lines' colours (Stephen, 2026-11-03)", () => {
  const trains = [
    { line: "Orange Line", toward: "New Carrollton" },
    { line: "Silver Line", toward: "New Carrollton" },
    { line: "Blue Line", toward: "Downtown Largo" },
    { line: "Silver Line", toward: "Downtown Largo" },
  ];
  assert.deepEqual(boardingGroups(trains, "Stadium-Armory"), [
    { lines: ["Orange Line", "Silver Line"], toward: "New Carrollton" },
    { lines: ["Blue Line", "Silver Line"], toward: "Downtown Largo" },
  ]);
  // Signed to the stop the rider gets off at: no end shown.
  assert.deepEqual(boardingGroups([{ line: "Red Line", toward: "Glenmont" }], "Glenmont"), [{ lines: ["Red Line"], toward: null }]);
  assert.deepEqual(lineBadge("Red Line"), { background: "#bf0d3e", color: "#ffffff" });
  assert.equal(lineBadge("Yellow Line")!.color, "#111827");
  assert.equal(lineBadge("Blue Line")!.color, "#111827");
  assert.equal(lineBadge("Green Line")!.color, "#111827");
  assert.deepEqual(lineBadge("MARC Penn Line"), { background: "#8a6500", color: "#ffffff" });
  assert.equal(lineBadge("C53"), null);
  // The leg carries every train that will do, from the API's `towards`; one, the planned way, from an older API.
  const step = { mode: "metro", lines: ["Orange Line", "Silver Line"], wait_s: 120, toward: "New Carrollton", stops: [{ name: "A", point: [0, 0], after_s: 0 }, { name: "B", point: [0, 0.01], after_s: 60 }] } as unknown as TransitStep;
  assert.deepEqual(onBoardLeg({ ...step, towards: [{ line: "Orange Line", toward: "New Carrollton" }, { line: "Silver Line", toward: "New Carrollton" }] })!.trains!.length, 2);
  assert.deepEqual(onBoardLeg(step)!.trains, [{ line: "Orange Line / Silver Line", toward: "New Carrollton" }]);
});

test("the ride screen shows the boarding as rows, its departure countdown only where it is this boarding's", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /<BoardingCard leg=\{boardingLeg\} departure=\{boardingDeparture\} note=/);
  assert.match(ride, /const boardingDeparture = trip\?\.departure && trip\.boardStep != null && trip\.departure\.step === trip\.boardStep \? trip\.departure : null;/);
  assert.match(ride, /<DepartureTimer departure=\{trip\.departure\} announce=\{notify\} noticeOnly=\{!!boardingLeg && !!boardingDeparture\} \/>/);
});

test("the next live trains are the ones that make the ride, soonest first, each named (Stephen, 2026-11-03)", () => {
  const groups = [
    { lines: ["Orange Line", "Silver Line"], toward: "New Carrollton" },
    { lines: ["Blue Line", "Silver Line"], toward: "Downtown Largo" },
  ];
  const stops = [{ name: "Federal Triangle" }, { name: "Smithsonian" }, { name: "Eastern Market" }];
  const live = [
    { line: "Silver Line", toward: "Downtown Largo", minutes: [7, 19] },
    { line: "Orange Line", toward: "New Carrollton", minutes: [3] },
    // The other way, and a line that does not make the ride: skipped.
    { line: "Orange Line", toward: "Vienna", minutes: [1] },
    { line: "Red Line", toward: "Glenmont", minutes: [0] },
    // A short turn that ends at the rider's stop makes it; one that turns back before it does not.
    { line: "Blue Line", toward: "Eastern Market", minutes: [12] },
    { line: "Silver Line", toward: "Smithsonian", minutes: [5] },
  ];
  assert.deepEqual(liveForBoarding(live, groups, stops).slice(0, 3), [
    { line: "Orange Line", toward: "New Carrollton", minutes: 3 },
    { line: "Silver Line", toward: "Downtown Largo", minutes: 7 },
    { line: "Blue Line", toward: "Eastern Market", minutes: 12 },
  ]);
  assert.deepEqual(liveForBoarding([], groups, stops), []);
  assert.equal(liveNextText(3), "3 min");
  assert.equal(liveNextText(0), "Arriving");
});

test("a live train goes the ride's way by where WMATA says it ends, never by its name alone", () => {
  const groups = [{ lines: ["Orange Line", "Silver Line"], toward: "New Carrollton" }];
  const triangle: [number, number] = [-77.0282, 38.8937];
  const market: [number, number] = [-76.995334, 38.884124];
  const stops = [
    { name: "Federal Triangle", point: triangle },
    { name: "Eastern Market", point: market },
  ];
  const live = [
    // Signed differently from the schedule's end, but ending past the rider's stop: it makes the ride.
    { line: "Orange Line", toward: "NewCrltn", end: [-76.8718, 38.9478] as [number, number], minutes: [4] },
    // Ends the other way, or short of the stop: skipped.
    { line: "Silver Line", toward: "Vienna/Fairfax-GMU", end: [-77.2716, 38.8779] as [number, number], minutes: [2] },
    { line: "Orange Line", toward: "Smithsonian", end: [-77.028, 38.8881] as [number, number], minutes: [1] },
  ];
  assert.deepEqual(liveForBoarding(live, groups, stops), [{ line: "Orange Line", toward: "NewCrltn", minutes: 4 }]);
});

test("without WMATA's end, a train's line and name must belong together; names compare without punctuation", () => {
  const groups = [
    { lines: ["Orange Line"], toward: "Vienna/Fairfax-GMU" },
    { lines: ["Silver Line"], toward: "Ashburn" },
  ];
  const stops = [{ name: "Rosslyn" }, { name: "Ballston-MU" }];
  const live = [
    { line: "Orange Line", toward: "Vienna Fairfax GMU", minutes: [3] },
    // Orange is a ride line and Ashburn a ride end, but no Orange train goes to Ashburn.
    { line: "Orange Line", toward: "Ashburn", minutes: [1] },
  ];
  assert.deepEqual(liveForBoarding(live, groups, stops), [{ line: "Orange Line", toward: "Vienna Fairfax GMU", minutes: 3 }]);
});

test("live minutes count down from the reading's time, and a reading too old says nothing", () => {
  const groups = [{ lines: ["Red Line"], toward: "Glenmont" }];
  const stops = [{ name: "Union Station" }, { name: "Glenmont" }];
  const live = [{ line: "Red Line", toward: "Glenmont", minutes: [1, 6] }];
  const asOf = "2026-11-03T18:00:00-05:00";
  const t0 = Date.parse(asOf);
  assert.deepEqual(
    liveForBoarding(live, groups, stops, { asOf, nowMs: t0 + 2 * 60_000 }).map((x) => x.minutes),
    [4],
  );
  assert.deepEqual(liveForBoarding(live, groups, stops, { asOf, nowMs: t0 + 4 * 60_000 }), []);
});

// Stephen, 2026-11-04: "When on transit, put the approximate time left to arrival. Also, if you can show the path too."
test("time left on board: none while waiting; the timetable's run from the stop reached, held at the next stop when late", () => {
  const t0 = 1_000_000;
  // Waiting: no time left shown (the boarding card has the departure).
  assert.equal(onBoardSecondsLeft(LEG, { at: 0, boardedAt: null }, t0), null);
  // Just boarded at Takoma: the whole run, 10 min.
  assert.equal(onBoardSecondsLeft(LEG, { at: 0, boardedAt: t0 }, t0), 600);
  // A minute on: 9 min left.
  assert.equal(onBoardSecondsLeft(LEG, { at: 0, boardedAt: t0 }, t0 + 60_000), 540);
  // Five minutes on, still short of Fort Totten (a late train): held at Fort Totten's, 8 min.
  assert.equal(onBoardSecondsLeft(LEG, { at: 0, boardedAt: t0 }, t0 + 300_000), 480);
  // The fix says Rhode Island Ave already (an early train, a late boarding seen): from there, 4 min.
  assert.equal(onBoardSecondsLeft(LEG, { at: 3, boardedAt: t0 }, t0 + 60_000), 240);
  // At the stop to get off: none left.
  assert.equal(onBoardSecondsLeft(LEG, { at: 5, boardedAt: t0 }, t0 + 900_000), 0);
});

test("the trip's end after the stop to get off: every later step's time and wait, from the plan", () => {
  const exit: TransitStep = { ...STEP, mode: "exit", text: "Leave the station.", seconds: 90, wait_s: 0, lines: [], stops: null };
  const ride: TransitStep = { ...STEP, mode: "ride", text: "Ride to the end.", seconds: 420, wait_s: 0, lines: [], stops: null, coordinates: [north(6000), north(7000)] };
  const enter: TransitStep = { ...STEP, mode: "enter", text: "Into the station.", seconds: 60, wait_s: 0, lines: [], stops: null };
  const parts = onwardOf([{ ...STEP, mode: "ride", route_line: true, coordinates: [] }, enter, STEP, exit, ride], 0);
  const train = parts.find((p) => p.kind === "transit");
  assert.ok(train && train.kind === "transit");
  assert.equal(train.leg.afterS, 510);
  // From onBoardLeg alone (no plan around it): not known.
  assert.equal(LEG.afterS, null);
});

test("the path on the map: the stops ahead in the line's colour, the one to get off marked; a bus names it", () => {
  const waiting = onBoardPath(LEG, 0)!;
  assert.equal(waiting.coordinates.length, 6);
  assert.equal(waiting.colour, lineColour(["Red Line"]));
  assert.notEqual(waiting.colour, null);
  assert.deepEqual(
    waiting.stops.map((s) => s.off),
    [false, false, false, false, false, true],
  );
  // Three stops on: only the rest drawn; at the stop before the last, still a line to it.
  assert.equal(onBoardPath(LEG, 3)!.coordinates.length, 3);
  assert.equal(onBoardPath(LEG, 5)!.coordinates.length, 2);
  // A line with no colour of its own: the map's transit colour.
  const bus = onBoardLeg({ ...STEP, mode: "bus", lines: ["B10"], towards: null })!;
  const busPath = onBoardPath(bus, 0)!;
  assert.equal(busPath.colour, null);
  const features = onBoardFeatures(busPath).features as { geometry: { type: string }; properties: { colour: string; off?: boolean; bus?: boolean } }[];
  assert.equal(features[0].geometry.type, "LineString");
  assert.equal(features.length, 7);
  assert.ok(features.every((f) => /^#/.test(f.properties.colour)));
  assert.deepEqual(features.filter((f) => f.properties.off).length, 1);
  assert.equal(onBoardFeatures(null).features.length, 0);
});

// Stephen, 2026-11-04: "It also has an erroneous you have arrived when pressing the map center button" (on the train).
test("Where am I? on transit: the line and stop to get off while waiting; the stops and time left on board; never 'arrived'", () => {
  const exit: TransitStep = { ...STEP, mode: "exit", text: "Leave the station.", seconds: 90, wait_s: 0, lines: [], stops: null };
  const parts = onwardOf([{ ...STEP, mode: "ride", route_line: true, coordinates: [] }, STEP, exit], 0);
  const t0 = 1_000_000;
  const waiting = onwardWhere(parts, onwardStart(parts, t0), t0)!;
  assert.deepEqual(waiting.shown, ["Red Line toward Shady Grove", "Get off at Union Station"]);
  assert.ok(!/arrived/i.test(waiting.spoken));
  const state = onwardStart(parts, t0);
  const riding = { ...state, board: { ...state.board!, boardedAt: t0, at: 2 } };
  const on = onwardWhere(parts, riding, t0 + 60_000)!;
  assert.equal(on.shown[1].startsWith("3 stops left · 6 min"), true);
  assert.match(on.spoken, /^Red Line toward Shady Grove\. Get off at Union Station\. 3 stops left, about 6 min, arriving about /);
  // Nothing followed any more: the line's own answer stands.
  assert.equal(onwardWhere(parts, { ...state, index: parts.length }, t0), null);
  assert.equal(onwardWhere([], null, t0), null);
});

test("the path follows the line's track where the API sent one, from the stop reached", () => {
  // A track with a bend between each pair of stops: twice the stops, less one.
  const track: LonLat[] = [];
  NAMES.forEach((_, i) => {
    track.push(north(i * 1200));
    if (i < NAMES.length - 1) track.push([-76.995, 38.9 + (i * 1200 + 600) / M_PER_DEG]);
  });
  const leg = onBoardLeg({ ...STEP, coordinates: track })!;
  assert.equal(leg.track?.length, 11);
  const waiting = onBoardPath(leg, 0)!;
  assert.equal(waiting.coordinates.length, 11);
  // At Rhode Island Ave (stop 3): the track from there, its bends kept.
  const on = onBoardPath(leg, 3)!;
  assert.deepEqual(on.coordinates[0], north(3600));
  assert.equal(on.coordinates.length, 5);
  // Stops-only coordinates (an older schedule): no track, stop to stop.
  assert.equal(LEG.track, null);
});
