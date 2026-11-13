// Cargo Bike's two choices in Plan's ride type dialog (Stephen 2026-10-25, "Fill this space"): the card takes
// two grid rows so the next ride type moves up beside the choices; each choice shows a few words, and a screen
// reader hears the full sentence once.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { CARRYINGS } from "./lib/dials.ts";

const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
// What the picker shows and says is rendered and checked in RideTypePicker.test.tsx; the grid is layout, which only a
// browser draws, so its rule is read here.

test("each load has a short summary, shorter than its full hint", () => {
  for (const load of CARRYINGS) {
    assert.ok(load.summary.length > 0 && load.summary.length < load.hint.length, load.id);
  }
});

test("the Cargo Bike card spans two rows of the dialog's grid, on a subgrid", () => {
  const rule = css.match(/\.ride-types \.ride-type-card\.with-loads \{([^}]*)\}/)?.[1] ?? "";
  assert.match(rule, /grid-row: span 2/);
  assert.match(rule, /grid-template-rows: subgrid/);
  assert.match(css, /\.ride-type-loads button \{[^}]*align-content: start/);
});
