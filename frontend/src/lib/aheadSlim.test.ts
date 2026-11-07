import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const graph = readFileSync(new URL("../AheadGraph.tsx", import.meta.url), "utf8");

test("the stress ribbon is thin and carries no level numbers (Stephen, 2026-11-07)", () => {
  assert.match(graph, /^const RIBBON_H = 8;$/m);
  assert.doesNotMatch(graph, /className="ride-ahead-level"/);
  // The levels are still said.
  assert.match(graph, /`\$\{AHEAD_HEADING\.stress\}: \$\{stressSentence\(ribbon, w\.youM\)\}`/);
});

test("graphs without room at their least are drawn slim: a short strip, a mark in the margin, no height axis (2026-11-07)", () => {
  assert.match(graph, /^const SLIM_H = 20;$/m);
  assert.match(graph, /if \(stripH \+ AXIS_H \+ k \* \(SLIM_H \+ GAP\) <= budget \+ GRACE_PX \* unit\) return k;/);
  assert.match(graph, /const h = slim \? SLIM_H : plotHeight\(shown\.length, budget, fixed\);/);
  assert.match(graph, /\{panels\.slim \? \(\s*\/\/[^\n]*\n\s*<SlimMark view=\{view\} panel=\{panel\} \/>/);
  assert.match(graph, /\{!panels\.slim && <YAxis ticks=\{drawn\.yTicks\} panel=\{panel\} \/>\}/);
  // "No room" is told only once it has held, not for a note's moment as the ride starts.
  assert.match(graph, /window\.setTimeout\(\(\) => onNoRoom\?\.\(untold\.split\(","\) as AheadView\[\]\), NO_ROOM_HOLD_MS\)/);
});

test("the turns are never dropped for the slim graphs: their strip kept, or the turns drawn on the ribbon (Stephen, 2026-11-07: \"They are important\")", () => {
  assert.match(graph, /const withTurns = slimFit\(turnsH \+ ribbonH\);/);
  assert.match(graph, /onRibbon: onRibbon && ribbonDrawn,/);
  // Drawn after the ribbon so its colours do not cover them, each on a halo.
  assert.match(graph, /<Ribbon [\s\S]*?\{panels\.onRibbon && <Turns marks=\{drawnTurns\} x=\{x\} cy=\{RIBBON_BLOCK \/ 2 - 1\} halo \/>\}/);
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
  assert.match(css, /\.ride-ahead-arrow-halo \{[^}]*stroke: var\(--bg\);/);
});
