// The Ride graph's turns row as the rider sees it, rendered (testSupport/render.ts): stops beside the turns
// (Stephen 2026-11-19: "Add the stop symbol to the same place as the turns on the traffic stress graph").
import { test } from "node:test";
import assert from "node:assert/strict";
import { render } from "./testSupport/render.ts";
import { AheadGraph } from "./AheadGraph.tsx";
import type { RouteResponse } from "./lib/api.ts";
import type { Cue } from "./lib/navigate.ts";
import { spreadMarks, turnMarks } from "./lib/aheadGraph.ts";
import { stopCardParts, stopPointIndex } from "./lib/navigate.ts";

const ROUTE = { profile: null, stress_spans: [{ from_m: 0, to_m: 3000, tier: 2, facility: null }], trail_levels: null } as unknown as RouteResponse;
type GraphCue = Pick<Cue, "kind" | "atM" | "movement" | "severity" | "joined" | "cross" | "source" | "stop" | "point">;
const cue = (over: Partial<GraphCue>): GraphCue => ({ kind: "turn", atM: 0, movement: null, severity: null, source: "stretch", stop: null, ...over });
const CUES: GraphCue[] = [
  cue({ atM: 300, movement: "left" }),
  cue({ kind: "stop", atM: 900, stop: 1, point: 1, source: "via" }),
  cue({ kind: "stop", atM: 1800, stop: 2, point: 2, source: "via" }),
];
const coffeeAtTwo = (c: Pick<Cue, "kind" | "point" | "stop">) => (stopPointIndex(c) === 2 ? ("coffee" as const) : undefined);

test("a stop is drawn in the turns' row: its icon where it has one, its number in a disc where not", async () => {
  const screen = await render(<AheadGraph views={["stress"]} route={ROUTE} cues={CUES} stopIcon={coffeeAtTwo} youM={0} lengthM={3000} />);
  const turns = screen.container.querySelector(".ride-ahead-turns");
  assert.ok(turns, "the turns row is drawn");
  assert.equal(turns.querySelectorAll(".ride-ahead-arrow").length, 1, "the turn keeps its arrow");
  const stops = [...turns.querySelectorAll(".ride-ahead-stop")];
  assert.equal(stops.length, 2, "both stops, in the same row as the turn");
  assert.equal(stops[0].textContent, "1", "no icon: the stop's number");
  assert.ok(stops[1].querySelector("image"), "an icon: the stop's picture");
  assert.equal(stops[1].textContent, "", "an icon: no number over it");
});

test("a stop beside a busy junction: both drawn, neither hiding the other", () => {
  const marks = turnMarks([cue({ atM: 100, movement: "right", severity: "red" }), cue({ kind: "stop", atM: 120, stop: 3, source: "via" })], { fromM: 0, toM: 3000 });
  const drawn = spreadMarks(marks, 50);
  assert.equal(drawn.length, 2);
  assert.equal(drawn[0].severity, "red", "the red turn kept");
  assert.deepEqual(drawn[1].stop, { number: 3, icon: null }, "the stop kept");
});

test("a named stop's card: the name large, 'Stop 2.' and where it is in the small print; no name, no change", () => {
  assert.deepEqual(stopCardParts({ kind: "stop", stop: 2, stopName: "Joe's Coffee", side: "right" }), { head: "Joe's Coffee", rest: "Stop 2. Destination on your right." });
  assert.deepEqual(stopCardParts({ kind: "stop", stop: 2, stopName: "Joe's Coffee" }), { head: "Joe's Coffee", rest: "Stop 2." });
  assert.equal(stopCardParts({ kind: "stop", stop: 2 }), null);
  assert.equal(stopCardParts({ kind: "turn", stop: null, stopName: "x" }), null);
});
