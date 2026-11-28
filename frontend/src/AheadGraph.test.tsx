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
type GraphCue = Pick<Cue, "kind" | "atM" | "movement" | "severity" | "ratedLevel" | "joined" | "cross" | "source" | "stop" | "point" | "then" | "exit">;
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

// Rated junctions (the owner, 2026-11-15: a dot at each crossing rated 3 or more, in its stress colour).
test("a rated junction on the ribbon: a small colour dot in place of the triangle, a rated turn's arrow in that level's colour", async () => {
  const { ratedDotFill } = await import("./lib/intersectionMarkers.ts");
  const cues = [
    cue({ kind: "hazard", atM: 400, severity: "red", source: "junction", ratedLevel: 4 }),
    cue({ atM: 1200, movement: "left", severity: "orange", ratedLevel: 3 }),
    cue({ kind: "hazard", atM: 2000, severity: "orange", source: "junction" }),
  ];
  const screen = await render(<AheadGraph views={["stress"]} route={ROUTE} cues={cues} youM={0} lengthM={3000} />);
  const turns = screen.container.querySelector(".ride-ahead-turns");
  assert.ok(turns);
  const dots = [...turns.querySelectorAll(".rated-dot")];
  assert.equal(dots.length, 1, "one dot: the rated junction that is not a turn");
  assert.equal(dots[0].getAttribute("aria-label"), "LTS 4");
  assert.equal(dots[0].textContent, "", "colour only: nothing written on the dot");
  const head = turns.querySelector<SVGPathElement>(".ride-ahead-arrow .ride-ahead-arrow-head");
  assert.equal(head?.style.fill, ratedDotFill(3), "the rated turn's arrow is in its level's colour");
  assert.equal(turns.querySelectorAll(":scope > path").length, 1, "the junction the model priced keeps its triangle");
});

test("rated marks drawn as one keep the harder level", () => {
  const marks = turnMarks(
    [cue({ atM: 100, movement: "right", severity: "orange", ratedLevel: 3 }), cue({ kind: "hazard", atM: 120, severity: "red", source: "junction", ratedLevel: 4.5 })],
    { fromM: 0, toM: 3000 },
  );
  assert.deepEqual(spreadMarks(marks, 50), [{ m: 100, movement: "right", severity: "red", rated: 4.5 }]);
});

// The owner, 2026-11-22: "Can it show the merged arrow?" Turns too close to draw apart, and a jog's turns, are one
// arrow through them all, as the cue card draws a jog.
test("turns too close to draw apart are one arrow through both, and a jog's turns too", async () => {
  const merged = spreadMarks(
    turnMarks([cue({ atM: 1000, movement: "right" }), cue({ atM: 1030, movement: "left", severity: "orange", ratedLevel: 3 })], { fromM: 0, toM: 3000 }),
    50,
  );
  assert.deepEqual(merged, [{ m: 1000, movement: "right", then: ["left"], severity: "orange", rated: 3 }]);
  const screen = await render(
    <AheadGraph
      views={["stress"]}
      route={ROUTE}
      cues={[cue({ atM: 1000, movement: "right" }), cue({ atM: 1010, movement: "left" }), cue({ atM: 2000, movement: "left", then: [{ movement: "right", street: null }] })]}
      youM={0}
      lengthM={3000}
    />,
  );
  const arrows = [...screen.container.querySelectorAll(".ride-ahead-turns .ride-ahead-arrow")];
  assert.equal(arrows.length, 2, "the close pair is one arrow, the jog another");
  for (const arrow of arrows) {
    const d = arrow.querySelector(".ride-ahead-arrow-jog")?.getAttribute("d") ?? "";
    assert.equal((d.match(/L/g) ?? []).length, 5, "one arrow with a leg after each of its two turns, and its head");
  }
});

test("a merged arrow keeps its colour, and turns one arrow cannot draw keep the first turn's own", async () => {
  const screen = await render(
    <AheadGraph
      views={["stress"]}
      route={ROUTE}
      cues={[
        cue({ atM: 500, movement: "right", severity: "orange" }),
        cue({ atM: 510, movement: "left" }),
        // Three rights wind back past a U: no one arrow, as on the cue card.
        cue({ atM: 1500, movement: "right", then: [{ movement: "right", street: null }, { movement: "right", street: null }] }),
      ]}
      youM={0}
      lengthM={3000}
    />,
  );
  const arrows = [...screen.container.querySelectorAll(".ride-ahead-turns .ride-ahead-arrow")];
  assert.equal(arrows.length, 2);
  assert.ok(arrows[0].classList.contains("ride-ahead-arrow-orange"), "the merged arrow in the worse colour");
  assert.ok(arrows[0].querySelector(".ride-ahead-arrow-jog"));
  assert.equal(arrows[1].querySelector(".ride-ahead-arrow-jog"), null, "the first turn's own arrow");
  // A circle's exit is never drawn into one arrow with other turns.
  const ring = turnMarks([cue({ atM: 100, movement: "right", exit: { number: 2 } as Cue["exit"], then: [{ movement: "left", street: null }] })], { fromM: 0, toM: 3000 });
  assert.equal(ring[0].then, undefined);
  assert.deepEqual(spreadMarks([...ring, { m: 120, movement: "left", severity: null }], 50).map((m) => [m.movement, m.then]), [["right", undefined]]);
});
