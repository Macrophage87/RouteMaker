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

test("mountain-bike trails ride on the ribbon in the map's colours, a rated level's sign on them, and are said (Stephen, 2026-11-07)", async () => {
  const { trailLevelMarks, trailLevelSentence } = await import("./aheadGraph.ts");
  const w = { fromM: 0, toM: 3000 };
  const marks = trailLevelMarks(
    [
      { from_m: 400, to_m: 700, level: 2 },
      { from_m: 700, to_m: 900, level: 2 },
      { from_m: 1200, to_m: 2900, level: 3 },
      { from_m: 2900, to_m: 2950, level: 0 },
      { from_m: 4000, to_m: 4500, level: 1 },
      { from_m: 100, to_m: 200, level: 7 },
    ],
    w,
  );
  assert.deepEqual(
    marks.map((m) => [m.fromM, m.toM, m.level, m.color]),
    [
      [400, 900, 2, "#1565c0"],
      [1200, 2900, 3, "#1c1917"],
      // "on unrated, give that a color too": the map's unrated trail brown.
      [2900, 2950, 0, "#7a5536"],
    ],
  );
  assert.match(trailLevelSentence(marks, 0), /^Blue trail \(level 2\) in .+, for .+\. Black trail \(level 3\) in .+, for .+\.$/);
  assert.match(trailLevelSentence(marks, 500), /^Blue trail \(level 2\) here, for /);
  assert.match(trailLevelSentence(marks, 2800), / Unrated mountain bike trail in .+, for .+\.$/);
  // Said with the ribbon; each rated level's sign drawn on it, clear of the turns where the stretch allows.
  assert.match(graph, /const trails = ribbon\.length && route\.trail_levels \? trailLevelMarks\(route\.trail_levels, w, route\.stress_spans\) : \[\];/);
  assert.match(graph, /facilitySentence\(rails, w\.youM\), trailLevelSentence\(trails, w\.youM\)\]/);
  assert.match(graph, /\{panels\.trails\.length > 0 && <TrailSigns marks=\{panels\.trails\} x=\{x\} cy=\{panels\.turnsH \+ RIBBON_BLOCK \/ 2\} turns=\{drawnTurns\} \/>\}/);
  assert.match(graph, /return spots\.find\(\(sx\) => room\(sx\) > TRAIL_SIGN \+ 6\) \?\? spots\.reduce\(\(a, b\) => \(room\(b\) > room\(a\) \? b : a\)\);/);
});

test("a trail stretch on the ribbon is its trail's colour, with brown rocks on its edges (Stephen, 2026-11-07)", () => {
  // "Use the trail color in the ribbon and brown dots that look like rocks on the edges."
  assert.match(graph, /<rect x=\{left\} y=\{band\} width=\{width\} height=\{RIBBON_H\} fill=\{trail\.color\} \/>/);
  assert.match(graph, /\{rocks\(left, width\)\.map\(\(rock, i\) => \(\s*<ellipse [^>]*fill=\{ROCK\} stroke=\{ROCK_EDGE\}/);
  assert.match(graph, /<Ribbon bars=\{panels\.ribbon\} rails=\{panels\.rails\} trails=\{panels\.trails\} /);
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
  assert.match(css, /\.ride-ahead-plot \.ride-ahead-mtb-bed \{\s*stroke: var\(--bg\);/);
});

test("the trail colour never covers an Avoid section, on the ribbon or the route line (#1025 review)", async () => {
  const { trailsBesideAvoid } = await import("./aheadGraph.ts");
  const cut = trailsBesideAvoid([{ from_m: 0, to_m: 1000, level: 3 }], [
    { from_m: 0, to_m: 300, tier: 2 },
    { from_m: 300, to_m: 450, tier: 5 },
    { from_m: 450, to_m: 1000, tier: 1 },
  ]);
  assert.deepEqual(cut, [
    { from_m: 0, to_m: 300, level: 3 },
    { from_m: 450, to_m: 1000, level: 3 },
  ]);
  const layers = readFileSync(new URL("./routeTrailLayers.ts", import.meta.url), "utf8");
  assert.match(layers, /for \(const span of trailsBesideAvoid\(found, route\.stress_spans\)\)/);
});
