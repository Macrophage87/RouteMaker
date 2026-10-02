// The measuring helper, checked against values that do not come from itself:
// the published CIEDE2000 test pairs (Sharma, Wu and Dalal, 2005) and the
// Python script the palette was chosen with (cvd.py, same matrices).
import { test } from "node:test";
import assert from "node:assert/strict";
import { adjacentDeltas, closestPair, deltaE2000, deltaE2000Lab, lab, simulate } from "./colourVision.ts";

test("CIEDE2000 reproduces Sharma, Wu and Dalal's published pairs", () => {
  const pairs: Array<[[number, number, number], [number, number, number], number]> = [
    [[50, 2.6772, -79.7751], [50, 0, -82.7485], 2.0425],
    [[50, 3.1571, -77.2803], [50, 0, -82.7485], 2.8615],
    [[50, 2.5, 0], [50, 0, -2.5], 4.3065],
    [[50, 2.5, 0], [73, 25, -18], 27.1492],
    [[50, 2.5, 0], [61, -5, 29], 22.8977],
    [[50, 2.5, 0], [56, -27, -3], 31.903],
    [[60.2574, -34.0099, 36.2677], [60.4626, -34.1751, 39.4387], 1.2644],
    [[2.0776, 0.0795, -1.135], [0.9033, -0.0636, -0.5514], 0.9082],
  ];
  for (const [a, b, expected] of pairs) {
    assert.ok(Math.abs(deltaE2000Lab(a, b) - expected) < 5e-4, `${a} vs ${b}: ${deltaE2000Lab(a, b)} not ${expected}`);
    assert.ok(Math.abs(deltaE2000Lab(b, a) - expected) < 5e-4, "symmetric");
  }
});

test("a colour is no distance from itself, and white is L 100", () => {
  assert.equal(deltaE2000("#5d99d2", "#5d99d2"), 0);
  assert.ok(Math.abs(lab("#ffffff")[0] - 100) < 0.01);
  assert.ok(Math.abs(lab("#000000")[0]) < 0.01);
});

test("the simulation matches the reference script's values", () => {
  const expected: Record<string, [string, string, string]> = {
    "#ff0000": ["#6d5f00", "#a39000", "#ff000f"],
    "#00ff00": ["#ffe500", "#efd63a", "#00f7d9"],
    "#0000ff": ["#0059ff", "#003dfb", "#006b96"],
    "#cd4b0a": ["#716300", "#918100", "#e22541"],
    "#5d99d2": ["#819bd5", "#728fd1", "#00a6ad"],
  };
  for (const [hex, [protan, deutan, tritan]] of Object.entries(expected)) {
    assert.equal(simulate(hex, "protan"), protan, `${hex} protan`);
    assert.equal(simulate(hex, "deutan"), deutan, `${hex} deutan`);
    assert.equal(simulate(hex, "tritan"), tritan, `${hex} tritan`);
    assert.equal(simulate(hex, "normal"), hex);
  }
});

test("greys and white are unchanged by every simulation", () => {
  for (const grey of ["#ffffff", "#808080", "#000000", "#202020"]) {
    for (const vision of ["protan", "deutan", "tritan"] as const) {
      const seen = simulate(grey, vision);
      const diff = [1, 3, 5].map((i) => Math.abs(parseInt(seen.slice(i, i + 2), 16) - parseInt(grey.slice(i, i + 2), 16)));
      assert.ok(Math.max(...diff) <= 1, `${grey} ${vision} -> ${seen}`);
    }
  }
});

test("the palette-measuring functions agree with the reference script", () => {
  assert.ok(Math.abs(deltaE2000("#cd4b0a", "#5d99d2") - 48.2681) < 1e-3);
  assert.ok(Math.abs(deltaE2000("#6a0a06", "#08081e") - 31.0902) < 1e-3);
  assert.ok(Math.abs(deltaE2000("#ff0000", "#00ff00") - 86.615) < 1e-3);
  const deltas = adjacentDeltas(["#ff0000", "#00ff00", "#0000ff"], "normal");
  assert.equal(deltas.length, 2);
  assert.ok(Math.abs(deltas[0] - 86.615) < 1e-3);
  const closest = closestPair(["#ff0000", "#ff0001", "#0000ff"], "normal");
  assert.deepEqual(closest.pair, [0, 1]);
});

test("a deficiency's confusion shows: red and green are close to a deuteranope, far to normal vision", () => {
  const colours = ["#ff0000", "#00ff00"];
  assert.ok(closestPair(colours, "normal").delta > 80);
  assert.ok(closestPair(colours, "deutan").delta < 40);
});
