import { test } from "node:test";
import assert from "node:assert/strict";
import { legMark, legsSaid, legsText, lineMark, linesMark } from "./transitMarks.ts";

test("Metro's lines are colour dots, said by name (colour is never the only cue)", () => {
  assert.deepEqual(lineMark("Metro", "Red Line"), { mark: "🔴", spoken: "Red Line" });
  assert.deepEqual(lineMark("wmata-rail", "Orange"), { mark: "🟠", spoken: "Orange Line" });
  for (const [line, dot] of [["Blue", "🔵"], ["Green", "🟢"], ["Yellow", "🟡"], ["Silver", "⚪"]]) {
    assert.equal(lineMark("Metro", `${line} Line`).mark, dot);
  }
  assert.deepEqual(linesMark("Metro", ["Orange Line", "Silver Line"]), { mark: "🟠⚪", spoken: "Orange Line or Silver Line" });
});

test("a bus by its route, MARC and VRE by their line, Baltimore's light rail and subway by their mark", () => {
  assert.deepEqual(lineMark("Metrobus", "C53", "bus"), { mark: "🚌C53", spoken: "bus C53" });
  assert.deepEqual(linesMark("Metrobus", ["C51", "C53"], "bus"), { mark: "🚌C51/C53", spoken: "bus C51 or C53" });
  assert.deepEqual(lineMark("MARC", "Penn Line", "rail"), { mark: "🚆Penn", spoken: "MARC Penn Line" });
  assert.equal(lineMark("MARC", "Camden Line").mark, "🚆Camden");
  assert.equal(lineMark("MARC", "Brunswick Line").mark, "🚆Brunswick");
  assert.deepEqual(lineMark("VRE", "Fredericksburg Line", "rail"), { mark: "🚆Fredericksburg", spoken: "VRE Fredericksburg Line" });
  assert.equal(lineMark("VRE", "Manassas Line").mark, "🚆Manassas");
  assert.deepEqual(lineMark("Light RailLink", "Light RailLink", "light-rail"), { mark: "🚈", spoken: "Light RailLink" });
  assert.deepEqual(lineMark("Metro SubwayLink", "Metro SubwayLink", "subway"), { mark: "🚇", spoken: "Metro SubwayLink" });
});

test("a trip's legs: emoji and minutes to see, words to hear", () => {
  const legs = [
    { mode: "walk", minutes: 4 },
    { mode: "bikeshare", minutes: 12 },
    { mode: "metro", minutes: 18, system: "Metro", lines: ["Red Line"] },
    { mode: "ride", minutes: 1 },
  ];
  assert.equal(legsText(legs), "🚶 4 min · 🚲 12 min · 🔴 18 min · 🚲 1 min");
  assert.equal(legsSaid(legs), "walk 4 minutes, bikeshare 12 minutes, Red Line 18 minutes, bike 1 minute");
  assert.equal(legMark({ mode: "bus", minutes: 9, system: "Metrobus", lines: ["C53"] }).mark, "🚌C53");
});
