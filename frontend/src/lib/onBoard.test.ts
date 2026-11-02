// Stop by stop on transit (Stephen, 2026-11-02): the stops followed by any fix that places the rider, a Wi-Fi fix
// underground too, else by the timetable; "Next stop" one before the rider's, then "Get off here".
import { test } from "node:test";
import assert from "node:assert/strict";
import type { TransitStep } from "./api.ts";
import type { LonLat } from "./geo.ts";
import type { RideFix } from "./navigate.ts";
import { STALE_MS, onBoardLeg, onBoardRows, onBoardStart, onBoardStep, stopsLeftText, type OnBoardState } from "./onBoard.ts";
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
  // A Wi-Fi fix at Brookland, 300 m out: on board, two stops on.
  go(2400, 300, 400_000);
  assert.ok(s.boardedAt !== null);
  assert.equal(s.at, 2);
  assert.deepEqual(said, []);
  assert.deepEqual(
    onBoardRows(LEG, s).map((r) => [r.name, r.next, r.off]).slice(2),
    [["Brookland-CUA", false, false], ["Rhode Island Ave", true, false], ["NoMa-Gallaudet U", false, false], ["Union Station", false, true]],
  );
  go(4800, 200, 600_000);
  assert.deepEqual(said, ["Next stop: Union Station. Get off there."]);
  go(4850, 200, 610_000);
  assert.equal(said.length, 1);
  go(6000, 100, 700_000);
  assert.deepEqual(said, ["Next stop: Union Station. Get off there.", "Get off here: Union Station."]);
  assert.equal(s.done, true);
  // A fix back down the line (a rough one) never moves the stops back.
  const after = onBoardStep(LEG, { ...s, done: false, at: 5 }, t0 + 710_000, fix(north(1200), 400, t0 + 710_000));
  assert.equal(after.state.at, 5);
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
  const t0 = 0;
  let s = onBoardStart(t0);
  // Nothing for a while: still waiting (the planned wait and STALE_MS have not run out).
  s = onBoardStep(LEG, s, 200_000).state;
  assert.equal(s.boardedAt, null);
  // Past the wait and STALE_MS: boarded at the end of the planned wait (240 s), stops by their scheduled seconds.
  s = onBoardStep(LEG, s, 240_000 + STALE_MS + 1).state;
  assert.equal(s.boardedAt, 240_000);
  const out1 = onBoardStep(LEG, s, 240_000 + 4 * 120_000 + 1000);
  assert.equal(out1.state.at, 4);
  assert.deepEqual(out1.said, ["Next stop: Union Station. Get off there."]);
  const out2 = onBoardStep(LEG, out1.state, 240_000 + 5 * 120_000 + 1000);
  assert.deepEqual(out2.said, ["Union Station should be about now, by the timetable. Get off there."]);
  assert.equal(out2.state.done, true);
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
