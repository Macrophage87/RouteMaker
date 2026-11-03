// Stop by stop on transit (Stephen, 2026-11-02): the stops followed by any fix that places the rider, a Wi-Fi fix
// underground too, else by the timetable; "Next stop" one before the rider's, then "Get off here".
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { TransitStep } from "./api.ts";
import type { LonLat } from "./geo.ts";
import type { RideFix } from "./navigate.ts";
import { STALE_MS, boardingGroups, laterDepartureText, lineBadge, nextDepartureText, onBoardLeg, onBoardRows, onBoardStart, onBoardStep, stopsLeftText, type OnBoardState } from "./onBoard.ts";
import { onwardOf, onwardStart, onwardStep } from "./onward.ts";

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

test("waiting to board, the card's next departure: a timed one's time and minutes, a frequent one's interval (Stephen, 2026-11-03)", () => {
  const departs_at = "2026-11-03T18:27:00-05:00";
  const at = Date.parse(departs_at);
  const timed = { departs: "6:27 pm", departs_at };
  assert.equal(nextDepartureText({ everyMin: null }, timed, at - 12 * 60_000), "6:27 pm, in 12 min");
  assert.equal(nextDepartureText({ everyMin: null }, timed, at - 30_000), "6:27 pm, in 1 min");
  assert.equal(nextDepartureText({ everyMin: null }, timed, at + 1000), "Now");
  // Long past: the time alone, never "Now" for ever.
  assert.equal(nextDepartureText({ everyMin: null }, timed, at + 5 * 60_000), "6:27 pm");
  assert.equal(nextDepartureText({ everyMin: 5 }, null, at), "every 5 min");
  // The plan's countdown is another step's: the step's own time.
  assert.equal(nextDepartureText({ everyMin: null, departs: "7:42 am" }, null, at), "7:42 am");
  assert.equal(nextDepartureText({ everyMin: null }, null, at), null);
  // The one after it, in case the rider can't make it.
  assert.equal(laterDepartureText({ next: "7:15 pm", next_at: "2026-11-03T19:15:00-05:00" }, at), "7:15 pm, in 48 min");
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
